"""The clearly labelled fictional catalog that local proofs and Clef's reference nodes publish.

Seeding drives a node's own API, so every record passes the same checks as an
organization's: import review, policy, authority evidence and publication consent.
Rerunning keeps existing records, edits and publication choices.
"""
import csv
import io

from services.policy_vocabulary import USAGE_KEYS, RESTRICTION_KEYS, default_ai_policy


class ApiClient:
    """Calls a node's API with one session; any non-success response stops the run."""

    def __init__(self, http, session_id):
        self.http = http
        self.headers = {"X-Session-Id": session_id}

    def call(self, method, path, body=None, **kwargs):
        response = self.http.request(method, path, headers=self.headers,
                                     **({"json": body} if body is not None else {}), **kwargs)
        if response.status_code not in {200, 201, 202}:
            # Never print a session, headers or private response.
            raise RuntimeError(f"Fixture operation {method} {path.split('?')[0]} failed ({response.status_code}); inspect private API logs")
        return response.json()


ISRC, ISWC = "ZZDEM2600001", "T1234567894"
TITLE, ARTIST = "Paper Skies", "Mara Vale (fictional)"


def seed(node, role):
    right = "master" if role == "label" else "composition"
    slug = f"connected-example-{role}"
    name = "Example Records · fictional" if role == "label" else "Example Publishing · fictional"
    context = node.call("GET", "/v1/session")
    org = next((row for row in context["organizations"] if row["slug"] == slug), None)
    if not org:
        org = node.call("POST", "/v1/organizations", {"slug": slug, "name": name,
            "organization_type": role, "default_territory": "US", "controlled_right_types": [right]})
    root = f"/v1/organizations/{org['id']}"
    work_key = f"isrc:{ISRC}" if role == "label" else f"iswc:{ISWC}"
    assets = node.call("GET", f"{root}/catalog/assets")["assets"]
    if not any(asset["workKey"] == work_key for asset in assets):
        clients = node.call("GET", f"{root}/catalog/clients")["clients"]
        if not any(row["externalReference"] == "mara-vale-fictional" for row in clients):
            node.call("POST", f"{root}/catalog/clients", {"name": ARTIST, "external_reference": "mara-vale-fictional"})
        data = io.StringIO(); writer = csv.writer(data)
        writer.writerow(["item_type", "title", "artist", "isrc", "iswc", "territory", "source_reference", "client_reference"])
        writer.writerow(["recording" if role == "label" else "work", TITLE, ARTIST,
            ISRC if role == "label" else "", ISWC, "US", "urn:clef:synthetic:connected-catalog-v1", "mara-vale-fictional"])
        batch = node.call("POST", f"{root}/catalog/imports/csv", files={"file": ("fictional.csv", data.getvalue().encode(), "text/csv")})
        if batch["status"] != "committed":
            node.call("POST", f"{root}/catalog/imports/{batch['id']}/commit", {"confirm_import": True, "expected_preview_digest": batch["previewDigest"]})
    policy = next((row for row in node.call("GET", f"{root}/rights")["policies"] if row["workKey"] == work_key), None)
    if not policy:
        component = "stems" if role == "label" else "composition_data"
        ai = default_ai_policy("blocked")
        ai["inputs"][component] = "requires_approval"
        ai["modelScopes"]["private_single_tenant"] = "requires_approval"
        ai["limits"] = {"maxSourceDurationSeconds": 30, "maxOutputDurationSeconds": 60,
            "maxLyricCharacters": 0, "sourceRetentionDays": 7, "embeddingRetentionDays": 7}
        policy = node.call("PUT", f"{root}/rights/{work_key}", {"artist_name": ARTIST, "expected_version": 0,
            "note": "Fictional connected-catalog example", "contract": {"policyVersion": "clef.rights-policy.v2",
                "matrix": {"usage": {key: "requires_approval" if key == "ai_grounded_generation" else "blocked" for key in USAGE_KEYS},
                    "restrictions": {key: "denied" if key in {"political", "likeness_voice_clone", "deceptive_endorsement"} else "allowed" for key in RESTRICTION_KEYS}},
                "aiPolicy": ai, "metadata": {"workTitle": TITLE, "synthetic": True,
                    "recordingIsrc": ISRC, "compositionIswc": ISWC, "pairingSource": "urn:clef:synthetic:connected-catalog-v1"}}})
    claims = node.call("GET", f"{root}/authority-claims")["claims"]
    claim = next((row for row in claims if row["rightsContractId"] == policy["id"]), None)
    if not claim:
        claim = node.call("POST", "/v1/authority-claims", {"org_id": org["id"], "rights_contract_id": policy["id"],
            "right_type": right, "territory": "US", "evidence": {"source": "fictional_local_fixture",
                "reference": "urn:clef:synthetic:connected-catalog-v1", "synthetic": True, "share": "100.0000"}})
    if claim["status"] == "self_asserted":
        node.call("POST", f"/v1/authority-claims/{claim['id']}/verify", {"evidence_note": "Synthetic mandate for this local demonstration"})
    publications = node.call("GET", f"{root}/catalog/publications")["publications"]
    publication = next((row for row in publications if row["authorityClaimId"] == claim["id"]), None)
    if not publication:
        publication = consent(node, root, claim["id"])
    return {"org": org, "root": root, "claim": claim, "policy": policy, "publication": publication, "workKey": work_key}


def consent(node, root, claim_id):
    preview = node.call("POST", f"{root}/catalog/publications/preview", {"authority_claim_id": claim_id})
    if preview["publicFields"]["synthetic"] is not True:
        raise RuntimeError("Only a clearly labelled synthetic publication may be seeded")
    return node.call("POST", f"{root}/catalog/publications", {"authority_claim_id": claim_id,
        "preview_digest": preview["previewDigest"], "confirm_publication": True})
