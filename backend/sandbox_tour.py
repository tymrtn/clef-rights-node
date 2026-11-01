"""A fictional tour that exercises the regular authenticated application API.

Only anonymous public-sandbox guests can create it. A database lease prevents
parallel tabs/workers from duplicating requests. Interrupted preparation resumes
from durable API records; existing decisions and changed policies are preserved.
"""
import copy
import csv
import datetime as dt
import hashlib
import io
import uuid
from contextvars import ContextVar

import httpx
from fastapi import Depends, Header, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from models import SandboxTourRecord

VERSION = "clef.sandbox-tour.v1"
ARTIST = "Mara Vale (fictional)"
TITLE = "Paper Skies"
_active_lease = ContextVar("sandbox_preparation_lease", default=None)
_mutation_lease = ContextVar("sandbox_mutation_lease", default=None)


def fence_tour_mutation(db):
    """Lock/renew the lease in the mutation's own database transaction.

    Context is set solely around internal preparation calls, never from a header.
    The atomic update holds the row lock until the endpoint commits its mutation;
    an expired worker cannot resume after a new worker takes over. Ordinary API
    calls are unchanged. Both SQLite and PostgreSQL serialize this update.
    """
    lease = _mutation_lease.get()
    if lease is None:
        return
    user_id, token = lease
    now = dt.datetime.utcnow()
    owned = db.query(SandboxTourRecord).filter(
        SandboxTourRecord.user_id == user_id, SandboxTourRecord.lease_token == token,
        SandboxTourRecord.lease_until >= now,
    ).update({"lease_until": now + dt.timedelta(minutes=5)}, synchronize_session=False)
    if not owned:
        db.rollback()
        raise HTTPException(409, "Example preparation changed workers. Reload the prepared example.")


async def _call(client, method, path, **kwargs):
    fence = _mutation_lease.set(_active_lease.get() if method in {"POST", "PUT", "PATCH", "DELETE"} else None)
    try:
        response = await client.request(method, path, **kwargs)
    finally:
        _mutation_lease.reset(fence)
    if not response.is_success:
        raise HTTPException(response.status_code, detail={
            "message": "Example preparation paused. Retry to resume the same records.",
            "operation": path, "cause": response.json().get("detail", "Request failed"),
        })
    return response.json()


def register_sandbox_tour(app, *, settings, get_db, require_user, default_ai_policy,
                          usage_keys, restriction_keys, safeguard_keys):
    def guest(db, token):
        if settings.NODE_DEPLOYMENT_MODE != "public_sandbox" or not settings.SANDBOX_GUEST_ACCESS:
            raise HTTPException(404, "Prepared examples are available in the public sandbox")
        user = require_user(db, token)
        if not (user.role == "admin" and user.email.startswith("sandbox-") and user.email.endswith("@sandbox.invalid")):
            raise HTTPException(403, "Start an anonymous sandbox session to explore this example")
        return user

    def transport(user_id):
        # No network requests: all catalog, policy and decision validation remains
        # in the application's real endpoints. Each guest has its own limiter key.
        return httpx.ASGITransport(app=app, client=(f"tour-{user_id}", 0))

    async def view(manifest, client):
        result = copy.deepcopy(manifest)
        for side in result["sides"]:
            side["permission"] = await _call(client, "GET", f"/v1/permission-requests/{side['permissionId']}")
            side["policy"] = await _call(client, "GET", f"/v1/organizations/{side['orgId']}/rights/{side['workKey']}")
            claims = await _call(client, "GET", f"/v1/organizations/{side['orgId']}/authority-claims")
            side["authority"] = next(c for c in claims["claims"] if c["id"] == side["request"]["authority_claim_id"])
        return result

    async def prepare(user_id, client):
        context = await _call(client, "GET", "/v1/session")
        suffix = user_id.replace("-", "")
        marker = f"urn:clef:synthetic:{suffix}"
        # These identifiers are explicitly illustrative; no registry lookup occurs.
        digits = str(int(hashlib.sha256(suffix.encode()).hexdigest(), 16)).zfill(12)
        isrc = f"ZZDEM{digits[-7:]}"
        base = digits[-9:]
        check = (10 - (1 + sum((i + 1) * int(c) for i, c in enumerate(base))) % 10) % 10
        iswc = f"T{base}{check}"

        async def organization(role, name, rights):
            slug = f"tour-{suffix}-{role}"
            existing = next((o for o in context["organizations"] if o["slug"] == slug), None)
            return existing or await _call(client, "POST", "/v1/organizations", json={
                "slug": slug, "name": name, "organization_type": role,
                "default_territory": "US", "controlled_right_types": rights,
            })

        requester = await organization("requester", "Example Studio · fictional", [])
        sides = []
        for role, name, right, identifier, asset in (
            ("label", "Example Records · fictional", "master", isrc, "stems"),
            ("publisher", "Example Publishing · fictional", "composition", iswc, "composition_data"),
        ):
            org = await organization(role, name, [right])
            root = f"/v1/organizations/{org['id']}"
            work_key = f"{'isrc' if role == 'label' else 'iswc'}:{identifier}"
            assets = (await _call(client, "GET", f"{root}/catalog/assets"))["assets"]
            if not any(asset["workKey"] == work_key for asset in assets):
                managed = (await _call(client, "GET", f"{root}/catalog/clients"))["clients"]
                client_ref = "mara-vale-fictional"
                if not any(item["externalReference"] == client_ref for item in managed):
                    await _call(client, "POST", f"{root}/catalog/clients", json={
                        "name": ARTIST, "external_reference": client_ref,
                    })
                catalog = io.StringIO()
                writer = csv.writer(catalog)
                writer.writerow(["item_type", "title", "artist", "iswc", "isrc", "territory", "source_reference", "client_reference"])
                writer.writerow(["recording" if role == "label" else "work", TITLE, ARTIST,
                                 iswc, isrc if role == "label" else "", "US", marker, client_ref])
                batch = await _call(client, "POST", f"{root}/catalog/imports/csv",
                    files={"file": ("fictional-catalog.csv", catalog.getvalue().encode(), "text/csv")})
                if batch["status"] != "committed":
                    await _call(client, "POST", f"{root}/catalog/imports/{batch['id']}/commit", json={"confirm_import": True, "expected_preview_digest": batch["previewDigest"]})

            policies = (await _call(client, "GET", f"{root}/rights"))["policies"]
            policy = next((p for p in policies if p["workKey"] == work_key), None)
            if not policy:
                ai = default_ai_policy("review_each_ai_use")
                ai["limits"] = {"maxSourceDurationSeconds": 30, "maxOutputDurationSeconds": 60,
                    "maxLyricCharacters": 0, "sourceRetentionDays": 7, "embeddingRetentionDays": 7}
                ai["inputs"] = {k: "requires_approval" if k == asset else "blocked" for k in ai["inputs"]}
                ai["modelScopes"] = {k: "requires_approval" if k == "private_single_tenant" else "blocked" for k in ai["modelScopes"]}
                policy = await _call(client, "PUT", f"{root}/rights/{work_key}", json={
                    "artist_name": ARTIST, "expected_version": 0, "note": "Fictional sandbox example",
                    "contract": {"policyVersion": "clef.rights-policy.v2",
                        "matrix": {"usage": {k: "requires_approval" if k == "ai_grounded_generation" else "blocked" for k in usage_keys},
                                   "restrictions": {k: "denied" if k in {"political", "likeness_voice_clone", "deceptive_endorsement"} else "allowed" for k in restriction_keys}},
                        "aiPolicy": ai, "metadata": {"workTitle": TITLE, "synthetic": True, "fixture": VERSION,
                            "pairingSource": marker, "recordingIsrc": isrc, "compositionIswc": iswc}},
                })
            claims = (await _call(client, "GET", f"{root}/authority-claims"))["claims"]
            claim = next((c for c in claims if c["rightsContractId"] == policy["id"]), None)
            if not claim:
                claim = await _call(client, "POST", "/v1/authority-claims", json={
                    "org_id": org["id"], "rights_contract_id": policy["id"], "right_type": right,
                    "territory": "US", "evidence": {"source": "fictional_sandbox_fixture", "synthetic": True,
                        "reference": marker, "evidenceUri": marker, "share": "100.0000", "note": "Illustrative mandate for this example only"},
                })
            if claim["status"] == "self_asserted":
                await _call(client, "POST", f"/v1/authority-claims/{claim['id']}/verify",
                    json={"evidence_note": "Fictional sandbox mandate reviewed for the prepared example"})
            existing = (await _call(client, "GET", f"/v1/organizations/{requester['id']}/permission-requests"))["permissionRequests"]
            permission = next((p for p in existing if p.get("context", {}).get("tourStep") == f"{marker}:{role}"), None)
            today = dt.datetime.now(dt.timezone.utc).date()
            request = {"requester_org_id": requester["id"], "authority_claim_id": claim["id"],
                "intended_usage": "ai_grounded_generation", "territory": "US",
                "term_start": today.isoformat(), "term_end": (today + dt.timedelta(days=90)).isoformat(),
                "context": {"tourStep": f"{marker}:{role}", "restrictionCategories": [],
                    "releaseTitle": "Paper Skies · 60-second instrumental study (fictional)",
                    "aiUse": {"inputAssets": [asset], "modelScope": "private_single_tenant",
                        "sourceDurationSeconds": 30, "outputDurationSeconds": 60, "lyricCharacters": 0,
                        "sourceRetentionDays": 7, "embeddingRetentionDays": 7, "acceptedSafeguards": list(safeguard_keys)}},
                "provenance": {"synthetic": True, "pairingSource": marker}}
            if not permission:
                permission = await _call(client, "POST", "/v1/permission-requests", json=request)
            detail = await _call(client, "GET", f"/v1/permission-requests/{permission['id']}")
            if detail["status"] == "pending" and not detail.get("reviewAssignment"):
                await _call(client, "POST", f"/v1/permission-requests/{permission['id']}/review-assignments",
                    json={"reviewer_user_id": user_id, "reason": "Sandbox guest plays the named reviewer in this fictional example"})
            sides.append({"role": role, "orgId": org["id"], "name": org["name"], "rightType": right,
                "workKey": work_key, "permissionId": permission["id"], "request": request})
        return {"version": VERSION, "synthetic": True, "title": TITLE, "artist": ARTIST,
            "identifiers": {"isrc": isrc, "iswc": iswc, "source": "Fictional catalog supplied for this example"},
            "requester": {"id": requester["id"], "name": requester["name"]}, "sides": sides}

    @app.get("/v1/sandbox/tour")
    async def get_tour(db=Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = guest(db, x_session_id)
        row = db.get(SandboxTourRecord, user.id)
        if not row or not row.manifest:
            raise HTTPException(404, "Prepare the fictional catalog to begin")
        async with httpx.AsyncClient(transport=transport(user.id), base_url="http://sandbox-internal.invalid",
                                     headers={"X-Session-Id": x_session_id}) as client:
            return await view(row.manifest, client)

    @app.post("/v1/sandbox/tour")
    async def start_tour(db=Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = guest(db, x_session_id)
        user_id = user.id
        row = db.get(SandboxTourRecord, user_id)
        if not row:
            db.add(SandboxTourRecord(user_id=user_id))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
        now = dt.datetime.utcnow()
        lease = uuid.uuid4().hex
        acquired = db.query(SandboxTourRecord).filter(SandboxTourRecord.user_id == user_id,
            or_(SandboxTourRecord.lease_until.is_(None), SandboxTourRecord.lease_until < now)).update(
                {"lease_token": lease, "lease_until": now + dt.timedelta(minutes=5)}, synchronize_session=False)
        db.commit()
        if not acquired:
            raise HTTPException(409, "Your example is already being prepared. Try again shortly.", headers={"Retry-After": "5"})
        active_lease = _active_lease.set((user_id, lease))
        try:
            async with httpx.AsyncClient(transport=transport(user_id), base_url="http://sandbox-internal.invalid",
                                         headers={"X-Session-Id": x_session_id}) as client:
                row = db.get(SandboxTourRecord, user_id)
                db.refresh(row)
                manifest = row.manifest or await prepare(user_id, client)
                updated = db.query(SandboxTourRecord).filter_by(user_id=user_id, lease_token=lease).update({"manifest": manifest})
                if not updated:
                    raise HTTPException(409, "Example preparation expired. Retry to resume.")
                db.commit()
                return await view(manifest, client)
        finally:
            _active_lease.reset(active_lease)
            db.rollback()
            db.query(SandboxTourRecord).filter_by(user_id=user_id, lease_token=lease).update({"lease_token": None, "lease_until": None})
            db.commit()
