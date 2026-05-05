# ba-str-deployment

Python automation tools for MicroStrategy deployments at Bundesagentur für Arbeit (BA).

## Branches

| Branch | Tool | Purpose |
|:---|:---|:---|
| [`versorgung`](../../tree/versorgung) | `versorgungs_skripte` | Automated project deployment with/without backup and environment routing (Design → Integration → Freigabe → Bereitstellung) |
| [`wartungsfenster`](../../tree/wartungsfenster) | `wartungsfenster_skripte` | Automated maintenance window management for SGB II Freigabe releases |

## Requirements

- Python 3.9+
- [mstrio-py](https://github.com/MicroStrategy/mstrio-py)
- Access to MicroStrategy Library REST API

## Setup

Each branch contains its own `README.md` with full setup and usage instructions.

Clone only the branch you need:

```bash
# Versorgung tool
git clone -b versorgung https://github.com/romansytnyk86/ba-str-deployment.git

# Wartungsfenster tool
git clone -b wartungsfenster https://github.com/romansytnyk86/ba-str-deployment.git
```

## Security

`deployment*.env` files contain credentials and are excluded from version control.
Never commit credentials. Copy the `deployment.env` template from each branch and fill in locally.
