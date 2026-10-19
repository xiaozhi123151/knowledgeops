# GitHub publication and privacy

This repository is a sanitized snapshot of the locally verified KnowledgeOps project.
Original Git history, provider credentials, private runtime data, model weights, indexes,
virtual environments and caches are excluded. The original local checkout is unchanged.

Host-specific project/home paths and machine names in text artifacts are replaced with
portable placeholders. Experimental measurements and labels are not recomputed or changed.
Historical commit IDs and pre-redaction hashes in reports refer to the original local run;
they do not claim byte identity for redacted log/environment files in this snapshot.
Raw frozen retrieval rankings and public source snapshots remain byte-identical when they
contain no private paths. See publication-manifest.json for per-file publication hashes.

Never commit .env or data/. Supply live API credentials locally or via deployment secrets.
The .env.example access key is a public offline-demo value, never a live credential.

Publication regression: 97 offline tests passed, 10 live tests deselected; Ruff passed.
This is a separate publication check; the historical 107-test actual integration result is retained.
