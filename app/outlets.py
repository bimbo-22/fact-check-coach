"""The source whitelist. `outlet_for_url` is the single gate every URL passes through."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import yaml

SOURCES_FILE = Path(__file__).with_name("sources.yaml")


@dataclass(frozen=True)
class Outlet:
    id: str
    name: str
    domains: tuple[str, ...]
    path_hint: str | None
    type: str
    bias_label: str
    bias_source: str

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "domains": list(self.domains),
            "type": self.type,
            "bias_label": self.bias_label,
            "bias_source": self.bias_source,
        }


@lru_cache
def load_sources() -> tuple[str, tuple[Outlet, ...]]:
    data = yaml.safe_load(SOURCES_FILE.read_text())
    outlets = tuple(
        Outlet(
            id=o["id"],
            name=o["name"],
            domains=tuple(o["domains"]),
            path_hint=o.get("path_hint"),
            type=o["type"],
            bias_label=o["bias_label"],
            bias_source=o["bias_source"],
        )
        for o in data["outlets"]
    )
    return str(data.get("bias_checked", "unchecked")), outlets


def all_outlets() -> tuple[Outlet, ...]:
    return load_sources()[1]


def host_of(url: str) -> str:
    try:
        host = (urlparse(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def outlet_for_url(url: str) -> Outlet | None:
    """Return the whitelisted outlet for a URL, or None. Accepts subdomains, rejects look-alikes."""
    if not url.lower().startswith(("http://", "https://")):
        return None
    host = host_of(url)
    if not host:
        return None
    for outlet in all_outlets():
        for domain in outlet.domains:
            if host == domain or host.endswith("." + domain):
                return outlet
    return None


def outlet_by_id(outlet_id: str) -> Outlet | None:
    return next((o for o in all_outlets() if o.id == outlet_id), None)
