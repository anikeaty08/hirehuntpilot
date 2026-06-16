from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PortalDefinition:
    key: str
    label: str
    login_url: str
    supports_apply: bool = True


PORTAL_DEFINITIONS: dict[str, PortalDefinition] = {
    "linkedin": PortalDefinition("linkedin", "LinkedIn", "https://www.linkedin.com/login"),
    "indeed": PortalDefinition("indeed", "Indeed", "https://secure.indeed.com/account/login"),
    "internshala": PortalDefinition("internshala", "Internshala", "https://internshala.com/login/user"),
    "naukri": PortalDefinition("naukri", "Naukri", "https://www.naukri.com/nlogin/login"),
    "unstop": PortalDefinition("unstop", "Unstop", "https://unstop.com/auth/login"),
    "shine": PortalDefinition("shine", "Shine", "https://www.shine.com/myshine/login/"),
}


def available_portals() -> list[str]:
    return list(PORTAL_DEFINITIONS.keys())
