"""Profile inheritance: a broadcaster profile over the norms it extends -> effective profile (SPEC §12).

Layers, applied in this order: the norms of ``meta.extends`` (a norm extended by another one
comes before it), then ``lumiris_maison`` (house rules, last of ``extends`` when cited), then the
profile itself. Dictionaries merge field by field; any other value (number, text, list, severity
chain) is replaced as a whole by a later layer, an explicit ``null`` included. Nothing here
depends on the date, the machine or the order of a directory listing: same files, same result.

Every leaf value of the effective profile keeps its origin (file and citation) and every value
redefined with a different value is listed as a conflict. The result is written to
``effective_profile.json`` by ``analyze`` and ``rerun``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from pad_checker.rules.profile import NormMeta, Profile, ProfileError, translate

SCHEMA_VERSION = 1
NORMS_DIR = "normes"
HOUSE = "lumiris_maison"  # house rules: above the international norms, below the broadcaster profile
REPO_NORMS = Path(__file__).resolve().parents[3] / NORMS_DIR
SEVERITY = "rules.severity"


@dataclass(frozen=True)
class Layer:
    kind: str  # "norm" | "profile"
    name: str
    file: str  # shown to the user: "normes/ebu_r128.yaml", "profiles/arte_hd_sdr.yaml"
    document: str
    sha256: str  # of the file with CRLF line ends turned into LF (same on every checkout)


@dataclass
class Origin:
    file: str
    source: str | None
    replaced: list[dict[str, Any]] = field(default_factory=list)  # earlier definitions: {file, value}


@dataclass
class Conflict:
    """A value redefined by a later layer with a different value."""

    path: str
    value: Any
    file: str
    replaced_value: Any
    replaced_file: str


@dataclass
class ResolvedProfile:
    profile: Profile
    profile_file: str
    layers: list[Layer]
    origins: dict[str, Origin]
    conflicts: list[Conflict]

    @property
    def values(self) -> dict[str, Any]:
        return profile_values(self.profile)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.profile)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "profile_file": self.profile_file,
            "name": self.profile.meta.name,
            "status": self.profile.meta.status,
            "fingerprint_sha256": self.fingerprint,
            "layers": [vars(layer) for layer in self.layers],
            "values": self.values,
            "origins": {path: vars(o) for path, o in self.origins.items()},
            "conflicts": [vars(c) for c in self.conflicts],
        }

    def dumps(self) -> str:
        return json.dumps(self.to_json(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _canonical(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def profile_values(profile: Profile) -> dict[str, Any]:
    """Effective values as JSON data: the fields given by a layer, explicit nulls included."""
    return profile.model_dump(mode="json", by_alias=True, exclude_unset=True)


def fingerprint(profile: Profile) -> str:
    """SHA-256 of the effective values in canonical JSON (shown in the report)."""
    return hashlib.sha256(_canonical(profile_values(profile)).encode("utf-8")).hexdigest()


def from_json(data: dict[str, Any], where: Path) -> ResolvedProfile:
    """Effective profile written by :meth:`ResolvedProfile.dumps` (``rerun`` without ``--profile``)."""
    try:
        profile = Profile.model_validate(data["values"])
        resolved = ResolvedProfile(
            profile=profile,
            profile_file=data["profile_file"],
            layers=[Layer(**layer) for layer in data["layers"]],
            origins={path: Origin(**o) for path, o in data["origins"].items()},
            conflicts=[Conflict(**c) for c in data["conflicts"]],
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise ProfileError(where, [f"profil effectif illisible ({exc.__class__.__name__}) : relancer « analyze »"]) from None
    if resolved.fingerprint != data.get("fingerprint_sha256"):
        raise ProfileError(where, ["l'empreinte ne correspond pas aux valeurs (fichier modifié à la main ?)"])
    return resolved


# --- files ---------------------------------------------------------------------------------


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(path, ["fichier introuvable"]) from None
    except yaml.YAMLError as exc:
        raise ProfileError(path, [f"YAML invalide : {exc}"]) from None
    if not isinstance(raw, dict):
        raise ProfileError(path, ["le fichier doit être un dictionnaire YAML"])
    return raw


def _meta_key(raw: dict[str, Any]) -> str:
    return "profile" if "profile" in raw and "meta" not in raw else "meta"


def is_norm(raw: dict[str, Any]) -> bool:
    meta = raw.get("meta")
    return isinstance(meta, dict) and meta.get("kind") == "norm"


def norms_dir_for(profile_path: Path) -> Path:
    """``normes/`` next to the profile's folder (profiles/../normes) if it exists, else the repository's."""
    sibling = profile_path.resolve().parent.parent / NORMS_DIR
    return sibling if sibling.is_dir() else REPO_NORMS


def _display(path: Path) -> str:
    return f"{path.parent.name}/{path.name}" if path.parent.name else path.name


# --- partial validation ----------------------------------------------------------------------


def _model_of(annotation: Any) -> type[BaseModel] | None:
    """The pydantic model inside ``X``, ``X | None``; None for any other type."""
    candidates = typing.get_args(annotation) if isinstance(annotation, types.UnionType) or \
        typing.get_origin(annotation) is typing.Union else (annotation,)
    for c in candidates:
        if isinstance(c, type) and issubclass(c, BaseModel):
            return c
    return None


def _field(model: type[BaseModel], key: str):
    for name, f in model.model_fields.items():
        aliases = {name, f.alias}
        choices = getattr(f.validation_alias, "choices", None)
        if choices:
            aliases |= set(choices)
        if key in aliases:
            return f
    return None


def check_partial(raw: dict[str, Any], model: type[BaseModel] = Profile, prefix: str = "") -> list[str]:
    """Field names and value types of a partial profile (a norm, or one layer). French messages.

    Whole-model rules (e.g. prefilter needs prefilter_taps) are checked on the effective profile.
    """
    errors: list[str] = []
    for key, value in raw.items():
        where = f"{prefix}{key}"
        f = _field(model, key)
        if f is None:
            errors.append(f"champ inconnu « {where} » (faute de frappe ?)")
            continue
        sub = _model_of(f.annotation)
        if sub is not None and isinstance(value, dict):
            errors += check_partial(value, sub, where + ".")
            continue
        try:
            TypeAdapter(f.annotation).validate_python(value)
        except ValidationError as exc:
            errors += [translate({**e, "loc": (*where.split("."), *e["loc"])}) for e in exc.errors()]
    return errors


# --- merge -----------------------------------------------------------------------------------


def leaves(data: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    """(dotted path, value) of every non-dictionary value (lists and severity chains are leaves)."""
    out: list[tuple[str, Any]] = []
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out += leaves(value, path + ".")
        else:
            out.append((path, value))
    return out


def source_of(path: str, value: Any, sources: dict[str, str]) -> str | None:
    """Citation of a leaf: its own entry of ``sources``, else the nearest parent entry.

    A severity chain cites itself (``source`` of each rule).
    """
    if path.startswith(SEVERITY + ".") and isinstance(value, list):
        cited = [r.get("source") for r in value if isinstance(r, dict) and r.get("source")]
        if cited:
            return " ; ".join(dict.fromkeys(cited))
    parts = path.split(".")
    while parts:
        key = ".".join(parts)
        if key in sources:
            return sources[key]
        parts.pop()
    return None


@dataclass
class _Merge:
    values: dict[str, Any] = field(default_factory=dict)
    origins: dict[str, Origin] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)

    def apply(self, layer: dict[str, Any], file: str, sources: dict[str, str]) -> None:
        self._merge(self.values, layer, file, sources, "")

    def _merge(self, base: dict[str, Any], layer: dict[str, Any], file: str, sources: dict[str, str],
               prefix: str) -> None:
        for key, value in layer.items():
            path = prefix + key
            if isinstance(value, dict) and value and isinstance(base.get(key), dict):
                self._merge(base[key], value, file, sources, path + ".")
                continue
            replaced = {p: o for p, o in self.origins.items() if p == path or p.startswith(path + ".")}
            old_leaves = dict(leaves({key: base[key]}, prefix)) if key in base else {}
            for p in replaced:
                del self.origins[p]
            base[key] = copy.deepcopy(value)
            new_leaves = dict(leaves({key: value}, prefix))
            for p, v in new_leaves.items():
                origin = Origin(file=file, source=source_of(p, v, sources))
                if p in replaced:
                    origin.replaced = replaced[p].replaced + [{"file": replaced[p].file, "value": old_leaves[p]}]
                self.origins[p] = origin
            for p, o in replaced.items():
                old = old_leaves[p]
                if p in new_leaves and new_leaves[p] == old:
                    continue  # same value restated: not a conflict
                new = new_leaves.get(p, value)  # absent: the whole subtree was replaced by ``value``
                self.conflicts.append(Conflict(path=p, value=new, file=file, replaced_value=old,
                                               replaced_file=o.file))


# --- resolution ------------------------------------------------------------------------------


@dataclass
class _Norm:
    name: str
    path: Path
    raw: dict[str, Any]
    meta: NormMeta


def load_norm(path: Path) -> _Norm:
    """A file of normes/, checked on its own: schema, name, a source for every value."""
    raw = read_yaml(path)
    try:
        meta = NormMeta.model_validate(raw.get("meta"))
    except ValidationError as exc:
        raise ProfileError(path, [translate(e, "meta.") for e in exc.errors()]) from None
    errors = []
    if meta.name != path.stem:
        errors.append(f"meta.name vaut {meta.name!r}, le fichier s'appelle {path.name}")
    body = {k: v for k, v in raw.items() if k not in ("meta", "sources")}
    sources = raw.get("sources") or {}
    if not isinstance(sources, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in sources.items()):
        errors.append("sources : dictionnaire « chemin.de.la.valeur: citation » attendu")
        sources = {}
    errors += check_partial(body)
    known = {p for p, _ in leaves(body)}
    for p, v in leaves(body):
        if source_of(p, v, sources) is None:
            errors.append(f"« {p} » : valeur sans source (ajouter « sources.{p} » : document et paragraphe)")
    for key in sources:
        if not any(p == key or p.startswith(key + ".") for p in known):
            errors.append(f"sources.{key} : aucune valeur à ce chemin")
    if errors:
        raise ProfileError(path, errors)
    return _Norm(name=meta.name, path=path, raw=body | {"sources": sources}, meta=meta)


def _norm_chain(names: list[str], norms_dir: Path, cited_by: str, stack: list[str],
                loaded: dict[str, _Norm], order: list[_Norm], profile_path: Path) -> None:
    for name in names:
        if name in stack:
            cycle = " → ".join(stack[stack.index(name):] + [name])
            raise ProfileError(profile_path, [f"cycle d'héritage : {cycle}"])
        if name in loaded:
            continue
        path = norms_dir / f"{name}.yaml"
        if not path.is_file():
            raise ProfileError(profile_path, [f"norme « {name} » introuvable : {path} (citée par {cited_by})"])
        norm = load_norm(path)
        _norm_chain(norm.meta.extends, norms_dir, f"normes/{name}.yaml", stack + [name], loaded, order, profile_path)
        loaded[name] = norm
        order.append(norm)


@dataclass
class Merged:
    """Layers merged, before the effective profile is validated (a draft may be incomplete)."""

    values: dict[str, Any]  # meta of the profile + merged sections
    profile_file: str
    layers: list[Layer]
    origins: dict[str, Origin]
    conflicts: list[Conflict]


def merge_layers(path: str | Path, norms_dir: Path | None = None) -> Merged:
    """The profile YAML at ``path`` merged over its norms, not validated. Raises ProfileError."""
    path = Path(path)
    raw = read_yaml(path)
    if is_norm(raw):
        raise ProfileError(path, ["ce fichier est une norme (meta.kind: norm), pas un profil de diffuseur"])
    meta_key = _meta_key(raw)
    meta = raw.get(meta_key)
    if not isinstance(meta, dict):
        raise ProfileError(path, [f"champ obligatoire manquant « {meta_key} »"])
    extends = meta.get("extends") or []
    if not isinstance(extends, list) or not all(isinstance(n, str) for n in extends):
        raise ProfileError(path, [f"« {meta_key}.extends » : liste de noms de normes attendue"])
    if len(set(extends)) != len(extends):
        raise ProfileError(path, [f"« {meta_key}.extends » : norme citée deux fois"])
    if HOUSE in extends and extends[-1] != HOUSE:
        raise ProfileError(path, [f"« {meta_key}.extends » : {HOUSE} (règles maison) doit être la dernière norme"])
    norms_dir = norms_dir or norms_dir_for(path)
    order: list[_Norm] = []
    _norm_chain(extends, norms_dir, _display(path), [], {}, order, path)

    sources = raw.get("sources") or {}
    if not isinstance(sources, dict):
        raise ProfileError(path, ["sources : dictionnaire « chemin.de.la.valeur: citation » attendu"])
    # The profile's own fields are checked with the effective profile (unknown, missing, wrong type).
    body = {k: v for k, v in raw.items() if k not in (meta_key, "sources")}

    merge = _Merge()
    layers = []
    for norm in order:
        layer = {k: v for k, v in norm.raw.items() if k != "sources"}
        merge.apply(layer, f"{NORMS_DIR}/{norm.name}.yaml", norm.raw["sources"])
        d = norm.meta.document
        layers.append(Layer(kind="norm", name=norm.name, file=f"{NORMS_DIR}/{norm.name}.yaml",
                            document=f"{d.title} ({d.version})", sha256=file_sha256(norm.path)))
    shown = _display(path)
    merge.apply(body, shown, sources)
    layers.append(Layer(kind="profile", name=str(meta.get("name", path.stem)), file=shown,
                        document=str(meta.get("source_document", "")), sha256=file_sha256(path)))

    return Merged(values={"meta": {"status": "draft", **meta}, **merge.values}, profile_file=shown, layers=layers,
                  origins=merge.origins, conflicts=merge.conflicts)


def resolve_profile(path: str | Path, norms_dir: Path | None = None) -> ResolvedProfile:
    """Effective profile of the profile YAML at ``path`` (SPEC §12.3). Raises ProfileError."""
    path = Path(path)
    m = merge_layers(path, norms_dir)
    try:
        profile = Profile.model_validate(m.values)
    except ValidationError as exc:
        raise ProfileError(path, [_with_origin(translate(e), e["loc"], m.origins, m.profile_file)
                                  for e in exc.errors()]) from None
    return ResolvedProfile(profile=profile, profile_file=m.profile_file, layers=m.layers, origins=m.origins,
                           conflicts=m.conflicts)


def _with_origin(message: str, loc: tuple[Any, ...], origins: dict[str, Origin], profile_file: str) -> str:
    """Name the norm a wrong value comes from, when it does not come from the profile itself."""
    path = ".".join(str(x) for x in loc if not isinstance(x, int))
    files = sorted({o.file for p, o in origins.items() if p == path or p.startswith(path + ".")} - {profile_file})
    return message + (f" (valeur héritée de {', '.join(files)})" if files else "")
