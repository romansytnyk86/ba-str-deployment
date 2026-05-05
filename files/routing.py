"""
routing.py – Quell-/Ziel-Umgebungsrouting für das Strategy Deployment Tool.

Definiert, welcher Workflow und welche Umgebungskonfiguration für jede
(Quelle, Ziel)-Kombination verwendet wird.

WIE MAN KONFIGURIERT
---------------------
1. ENVIRONMENT_CONFIGS: Hinterlege für jede Umgebung den Namen der
   zugehörigen deployment.env-Datei (z. B. deployment_integration.env).
   Alle relativen Pfade werden — wie beim --env-Argument — relativ zum
   files/-Verzeichnis aufgelöst.

2. ROUTING_MATRIX: Zeigt, welche (Quelle, Ziel)-Paare erlaubt sind und
   welcher Workflow jeweils ausgeführt wird. Diese Tabelle entspricht der
   fachlichen Freigabematrix (siehe Screenshot).

JENKINS-VERWENDUNG
------------------
Übergib --source-env und --target-env an main.py:

  python main.py --source-env Design --target-env Integration --backup-month 202604
  python main.py --source-env Integration --target-env Freigabe
  python main.py --source-env Design --target-env Design --backup-month 202604 --dry-run

Groß-/Kleinschreibung wird toleriert:
  --source-env design  →  wird als "Design" erkannt

WORKFLOW-ÜBERSICHT (ROUTING-MATRIX)
-------------------------------------
  Quelle       Ziel              Workflow
  ─────────────────────────────────────────────────────────────────────
  Design       Design            backup_duplicate       (Vormonatssuffix, gleiche Umgebung)
  Design       Abnahme           versorgung_merge       (cross-env, ggf. Merge)
  Design       Integration       backup_duplicate_then  (Backup dacg + Versorgung cross-env)
                                 _versorgung_merge
  Integration  Freigabe          versorgung_merge       (cross-env, ggf. Merge)
  Integration  Bereitstellung    versorgung_merge       (cross-env, ggf. Merge)
  ─────────────────────────────────────────────────────────────────────

MERGE-VERHALTEN
---------------
"Versorgung ggf. mit Merge" bedeutet: die Projekte werden von der
Quell-Umgebung in die Ziel-Umgebung übertragen. Die Methode richtet sich
nach BACKUP_METHOD in der Quell-Konfigurationsdatei:
  - BACKUP_METHOD=duplicate  → Duplizierung (Standard)
  - BACKUP_METHOD=merge      → Merge (sobald von mstrio unterstützt)
  - BACKUP_METHOD=package    → Paket-Migration
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Workflow-Typ-Konstanten
# ---------------------------------------------------------------------------

#: Deployment ohne Backup (nur Versorgung, kein Backup-Projekt).
WORKFLOW_WITHOUT_BACKUP = "without_backup"

#: Backupprojekt-Duplizierung (gleiche oder cross-env).
WORKFLOW_BACKUP_DUPLICATE = "backup_duplicate"

#: Versorgung ggf. mit Merge (cross-env; Methode steuert BACKUP_METHOD in .env).
WORKFLOW_VERSORGUNG_MERGE = "versorgung_merge"

#: Erst Backup-Duplizierung (dacg), dann Versorgung mit Merge (cross-env).
#: Wird für Design → Integration verwendet.
WORKFLOW_BACKUP_DUPLICATE_THEN_VERSORGUNG_MERGE = "backup_duplicate_then_versorgung_merge"


# ---------------------------------------------------------------------------
# Umgebungskonfiguration
# ---------------------------------------------------------------------------

@dataclass
class EnvironmentConfig:
    """Verbindungs- und Konfigurationsdetails für eine MicroStrategy-Umgebung."""

    #: Anzeigename – genau so wie er bei --source-env / --target-env angegeben wird.
    name: str

    #: Pfad zur deployment.env-Datei dieser Umgebung.
    #: Relative Pfade werden relativ zum files/-Verzeichnis aufgelöst (wie --env).
    env_file: str

    #: Lesbare Beschreibung – erscheint in Logs und Dry-Run-Ausgaben.
    description: str = ""


# ---------------------------------------------------------------------------
# Umgebungen und ihre Konfigurationsdateien
# HIER ANPASSEN: Für jede Umgebung den korrekten env_file-Pfad hinterlegen.
# ---------------------------------------------------------------------------

ENVIRONMENT_CONFIGS: dict[str, EnvironmentConfig] = {
    "Design": EnvironmentConfig(
        name="Design",
        env_file="deployment_design.env",
        description="Design / Entwicklungsumgebung",
    ),
    "Abnahme": EnvironmentConfig(
        name="Abnahme",
        env_file="deployment_abnahme.env",
        description="Abnahme / Test-Umgebung",
    ),
    "Integration": EnvironmentConfig(
        name="Integration",
        env_file="deployment_integration.env",
        description="Integrations-Umgebung",
    ),
    "Freigabe": EnvironmentConfig(
        name="Freigabe",
        env_file="deployment_freigabe.env",
        description="Freigabe / Pre-Production",
    ),
    "Bereitstellung": EnvironmentConfig(
        name="Bereitstellung",
        env_file="deployment_bereitstellung.env",
        description="Bereitstellung / Production",
    ),
}


# ---------------------------------------------------------------------------
# Routenkonfiguration
# ---------------------------------------------------------------------------

@dataclass
class RouteConfig:
    """Beschreibt Workflow und Anforderungen für ein (Quelle, Ziel)-Paar."""

    #: Eine der WORKFLOW_*-Konstanten oben.
    workflow: str

    #: True → --backup-month muss für diese Route angegeben werden.
    backup_month_required: bool

    #: Kurzbeschreibung (erscheint im Log-Header und in Dry-Run-Ausgaben).
    description: str

    #: Detailhinweise für Operator und Jenkins-Dokumentation.
    notes: str = ""


# ---------------------------------------------------------------------------
# DIE ROUTING-MATRIX
# Entspricht der fachlichen Freigabematrix (Quelle \ Ziel).
# Normalerweise muss hier nichts geändert werden.
# ---------------------------------------------------------------------------

ROUTING_MATRIX: dict[tuple[str, str], RouteConfig] = {

    # ── Design → Design ─────────────────────────────────────────────────────
    # Backupprojekt-Duplizierung mit Vormonatssuffix (gleiche Umgebung)
    ("Design", "Design"): RouteConfig(
        workflow=WORKFLOW_BACKUP_DUPLICATE,
        backup_month_required=True,
        description="Backupprojekt-Duplizierung mit Vormonatssuffix",
        notes=(
            "Erstellt eine Sicherungskopie des Projekts mit dem Vormonatssuffix "
            "auf der Design-Umgebung (gleiche Umgebung, kein Cross-Env). "
            "Beispiel: 'SGB II S2S' → 'SGB II S2S 202604'."
        ),
    ),

    # ── Design → Abnahme ────────────────────────────────────────────────────
    # Versorgung Projekte ggf. mit Merge
    ("Design", "Abnahme"): RouteConfig(
        workflow=WORKFLOW_VERSORGUNG_MERGE,
        backup_month_required=False,
        description="Versorgung Projekte ggf. mit Merge (Design → Abnahme)",
        notes=(
            "Überträgt die aktuellen Projekte von Design nach Abnahme (cross-env). "
            "Merge oder Duplizierung gemäß BACKUP_METHOD in der Quell-.env."
        ),
    ),

    # ── Design → Integration ────────────────────────────────────────────────
    # Schritt 1: Backupprojekt-Duplizierung mit Vormonatssuffix (dacg)
    # Schritt 2: Versorgung Projekte ggf. mit Merge
    ("Design", "Integration"): RouteConfig(
        workflow=WORKFLOW_BACKUP_DUPLICATE_THEN_VERSORGUNG_MERGE,
        backup_month_required=True,
        description="Backup-Duplizierung (dacg) + Versorgung ggf. mit Merge (Design → Integration)",
        notes=(
            "Schritt 1: Erstellt ein Backup-Projekt mit Vormonatssuffix (dacg) auf Integration. "
            "Schritt 2: Versorgt Integration mit den aktuellen Projekten aus Design "
            "(cross-env, Methode gemäß BACKUP_METHOD in der Quell-.env)."
        ),
    ),

    # ── Integration → Freigabe ──────────────────────────────────────────────
    # Versorgung Projekte ggf. mit Merge
    ("Integration", "Freigabe"): RouteConfig(
        workflow=WORKFLOW_VERSORGUNG_MERGE,
        backup_month_required=False,
        description="Versorgung Projekte ggf. mit Merge (Integration → Freigabe)",
        notes=(
            "Überträgt die aktuellen Projekte von Integration nach Freigabe (cross-env). "
            "Merge oder Duplizierung gemäß BACKUP_METHOD in der Quell-.env."
        ),
    ),

    # ── Integration → Bereitstellung ────────────────────────────────────────
    # Versorgung Projekte ggf. mit Merge
    ("Integration", "Bereitstellung"): RouteConfig(
        workflow=WORKFLOW_VERSORGUNG_MERGE,
        backup_month_required=False,
        description="Versorgung Projekte ggf. mit Merge (Integration → Bereitstellung)",
        notes=(
            "Überträgt die aktuellen Projekte von Integration nach Bereitstellung (cross-env). "
            "Merge oder Duplizierung gemäß BACKUP_METHOD in der Quell-.env."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Öffentliche Hilfsfunktionen
# ---------------------------------------------------------------------------

def get_route(source_env: str, target_env: str) -> RouteConfig:
    """
    Gibt die RouteConfig für das angegebene (Quelle, Ziel)-Paar zurück.

    Ist die Kombination nicht in der Matrix definiert, wird ValueError mit
    einer klaren Fehlermeldung und der Liste aller gültigen Routen geworfen.
    """
    source = _normalise_env(source_env)
    target = _normalise_env(target_env)

    key = (source, target)
    if key not in ROUTING_MATRIX:
        defined_routes = "\n    ".join(
            f"{s:15} →  {t}" for s, t in ROUTING_MATRIX
        )
        raise ValueError(
            f"Ungültige Kombination: '{source_env}' → '{target_env}'\n"
            f"  Definierte Routen:\n    {defined_routes}"
        )
    return ROUTING_MATRIX[key]


def get_env_config(env_name: str) -> EnvironmentConfig:
    """
    Gibt die EnvironmentConfig für den angegebenen Umgebungsnamen zurück.

    Ist die Umgebung nicht bekannt, wird ValueError mit einer klaren
    Fehlermeldung und der Liste aller bekannten Umgebungen geworfen.
    """
    name = _normalise_env(env_name)
    if name not in ENVIRONMENT_CONFIGS:
        known = ", ".join(ENVIRONMENT_CONFIGS)
        raise ValueError(
            f"Unbekannte Umgebung: '{env_name}'\n"
            f"  Bekannte Umgebungen: {known}"
        )
    return ENVIRONMENT_CONFIGS[name]


def describe_routing_matrix() -> str:
    """Gibt eine lesbare Übersicht der Routing-Matrix zurück (für Logs/Dry-Run)."""
    lines = [
        "Routing-Matrix (Quelle → Ziel → Workflow):",
        f"  {'Quelle':<15} {'Ziel':<18} {'Backup-Monat':<14} Beschreibung",
        "  " + "-" * 78,
    ]
    for (src, tgt), route in ROUTING_MATRIX.items():
        required = "erforderlich" if route.backup_month_required else "nicht nötig "
        lines.append(f"  {src:<15} {tgt:<18} {required:<14} {route.description}")
    return "\n".join(lines)


def _normalise_env(env_name: str) -> str:
    """
    Toleriert Groß-/Kleinschreibung: 'design' → 'Design'.
    Gibt den Namen unverändert zurück, wenn keine Übereinstimmung gefunden wird
    (der Aufrufer behandelt dann den fehlenden Schlüssel).
    """
    normalised = env_name.strip()
    for key in ENVIRONMENT_CONFIGS:
        if key.lower() == normalised.lower():
            return key
    return normalised
