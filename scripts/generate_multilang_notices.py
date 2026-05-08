"""Generate consent notices in the pack's full language set via foundation model.

Reads the en-IN notice from the active regulation pack's notices.yaml, calls
`databricks-gpt-oss-120b` (or whatever `persona_config.get_model_endpoint()`
returns) to translate into each non-seeded language listed in the pack's
languages.yaml, and MERGEs the resulting rows into
`compliance.notice_versions` so downstream views and consent events can link
to them.

For DPDP 2023, that means:
    seeded (hand-authored): en-IN, hi-IN, ta-IN           — 3 notices
    generated (this script): bn-IN, te-IN, mr-IN, gu-IN,  — 7 notices
                             kn-IN, ml-IN, pa-IN

Every generated notice carries a watermark preamble flagging it as machine-
translated, so downstream consumers can distinguish legal-reviewed copy
from demo-grade copy. For production use, replace the generated translations
with qualified legal-translator output before serving to principals.

Usage:
    python3 scripts/generate_multilang_notices.py                 # generate only missing
    python3 scripts/generate_multilang_notices.py --dry-run       # print prompts only
    python3 scripts/generate_multilang_notices.py --overwrite     # regenerate all non-seeded
    python3 scripts/generate_multilang_notices.py --language bn-IN  # one language only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from persona_config import get_warehouse_id, get_catalog, get_model_endpoint  # noqa: E402
from governance_core.pack_loader import active_pack  # noqa: E402


WATERMARK = (
    "[MACHINE-TRANSLATED — {model} on {date}. "
    "Review by a qualified legal translator required before production use.]\n\n"
)


def sql(stmt: str, wait: str = "30s") -> tuple[str, list, str]:
    """Run SQL via the statements API. Same pattern as tests/_sql.py."""
    payload = {"warehouse_id": get_warehouse_id(), "statement": stmt, "wait_timeout": wait}
    Path("/tmp/_multilang_sql.json").write_text(json.dumps(payload))
    r = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements",
         "--json", "@/tmp/_multilang_sql.json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ("ERR", [], r.stderr[:300])
    d = json.loads(r.stdout)
    state = d.get("status", {}).get("state", "UNKNOWN")
    if state != "SUCCEEDED":
        return (state, [], d.get("status", {}).get("error", {}).get("message", "")[:300])
    return ("OK", d.get("result", {}).get("data_array", []) or [], "")


def invoke_model(endpoint: str, system_prompt: str, user_prompt: str,
                 max_tokens: int = 2000, temperature: float = 0.2) -> str:
    """Invoke a Databricks serving endpoint via the CLI. Returns the
    assistant text. Raises RuntimeError on non-200 or malformed response."""
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    Path("/tmp/_multilang_model.json").write_text(json.dumps(payload))
    r = subprocess.run(
        ["databricks", "api", "post",
         f"/serving-endpoints/{endpoint}/invocations",
         "--json", "@/tmp/_multilang_model.json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"model invocation failed: {r.stderr[:400]}")
    try:
        body = json.loads(r.stdout)
        content = body["choices"][0]["message"]["content"]
    except (KeyError, json.JSONDecodeError) as e:
        raise RuntimeError(f"malformed model response: {e} — payload: {r.stdout[:300]}") from e

    # GPT-OSS returns a list of typed blocks: [{type: 'reasoning', summary: [...]},
    # {type: 'text', text: '...'}]. We want the text block. Older chat APIs
    # return the content as a plain string.
    if isinstance(content, list):
        for block in content:
            if block.get("type") == "text":
                return block.get("text", "").strip()
        raise RuntimeError(
            f"no text block in model response (got {len(content)} blocks, "
            f"types={[b.get('type') for b in content]}). "
            f"Likely truncated by max_tokens — try increasing."
        )
    return str(content).strip()


def build_translation_prompt(source_text: str, target_language: str,
                             target_script: str) -> tuple[str, str]:
    system = (
        "You are a professional legal translator specialising in India's Digital "
        "Personal Data Protection Act 2023. Translate the consent notice from "
        f"English (en-IN) into {target_language} (script: {target_script}). "
        "Preserve EXACTLY these elements — departure from any will be flagged "
        "by downstream validation:\n"
        "  (1) The numbered list structure — keep the digits '1.' through '6.' "
        "in Arabic numerals at the start of each list item, followed by the "
        "translated purpose text. Do NOT transliterate the digits into the "
        "target script's numeral system.\n"
        "  (2) Legal terms — consent, purposes, withdrawal, DPO — using the "
        "standard translations for that language.\n"
        "  (3) The line break pattern (blank lines between sections).\n"
        "  (4) The final citation. Keep the year '2023' in Arabic numerals "
        "(NOT '২০২৩' or '२०२३' or '೨೦೨೩' etc.). You may transliterate the "
        "phrase 'Digital Personal Data Protection Act' into the target script, "
        "but the year must stay as 2023 for legal-document consistency.\n"
        "Output ONLY the translated notice body. No commentary, disclaimers, "
        "or explanations outside the notice itself."
    )
    return system, source_text


def existing_language_ids(notice_id: str, version_number: int) -> set[str]:
    """Return the set of language codes already present for this notice+version."""
    state, rows, err = sql(
        f"SELECT language FROM {get_catalog()}.compliance.notice_versions "
        f"WHERE notice_id = '{notice_id}' AND version_number = {version_number}"
    )
    if state != "OK":
        print(f"  warn: could not list existing languages: {err}")
        return set()
    return {r[0] for r in rows}


def upsert_notice(row: dict) -> None:
    """MERGE a single notice row into compliance.notice_versions.

    The row dict must have the columns that table defines (notice_version_id,
    notice_id, version_number, language, legal_basis, notice_text,
    purposes_covered, effective_from, effective_to, approved_by, created_at).
    """
    def lit(v):
        if v is None:
            return "NULL"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, list):
            return "ARRAY(" + ", ".join(f"'{str(x).replace(chr(39), chr(39)*2)}'" for x in v) + ")"
        # String — escape single-quotes for SQL; \n stays inline in the value.
        s = str(v).replace("'", "''")
        return f"'{s}'"

    stmt = f"""
        MERGE INTO {get_catalog()}.compliance.notice_versions t
        USING (
          SELECT
            {lit(row['notice_version_id'])}   AS notice_version_id,
            {lit(row['notice_id'])}           AS notice_id,
            {lit(row['version_number'])}      AS version_number,
            {lit(row['language'])}            AS language,
            {lit(row['legal_basis'])}         AS legal_basis,
            {lit(row['notice_text'])}         AS notice_text,
            {lit(row['purposes_covered'])}    AS purposes_covered,
            CAST({lit(row['effective_from'])} AS TIMESTAMP) AS effective_from,
            CAST({lit(row['effective_to'])}   AS TIMESTAMP) AS effective_to,
            {lit(row['approved_by'])}         AS approved_by,
            CAST({lit(row['created_at'])}     AS TIMESTAMP) AS created_at
        ) s
        ON t.notice_version_id = s.notice_version_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """
    state, _, err = sql(stmt, wait="30s")
    if state != "OK":
        raise RuntimeError(f"MERGE failed for {row['notice_version_id']}: {err}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Print prompts + target languages without calling the model")
    p.add_argument("--overwrite", action="store_true",
                   help="Regenerate even for languages that already have a row")
    p.add_argument("--language", action="append",
                   help="Restrict to specific language codes (repeatable). "
                        "Default: every non-seeded language in the pack's languages.yaml")
    p.add_argument("--notice-id", default="marketing_notice",
                   help="Which notice_id to translate (default: marketing_notice)")
    p.add_argument("--version", type=int, default=1,
                   help="Notice version number (default: 1)")
    args = p.parse_args()

    pack = active_pack()
    endpoint = get_model_endpoint()
    catalog = get_catalog()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    watermark = WATERMARK.format(model=endpoint, date=today)

    print(f"Pack:     {pack.name} ({pack.code})")
    print(f"Endpoint: {endpoint}")
    print(f"Catalog:  {catalog}")

    # Find the seed notice (en-IN, notice_id+version).
    seed = next((n for n in pack.notices()
                 if n["notice_id"] == args.notice_id
                 and int(n["version_number"]) == args.version
                 and n["language"] == pack.primary_locale), None)
    if not seed:
        print(f"error: no seed notice for notice_id={args.notice_id} "
              f"version={args.version} language={pack.primary_locale}", file=sys.stderr)
        return 2

    print(f"Seed:     {seed['notice_version_id']} — {len(seed['notice_text'])} chars")

    # Determine target languages. Two different "seeded" concepts:
    #   pack_seeded_codes  — languages.yaml says seeded_by_poc:true, meaning
    #                        there's a hand-authored notice body that must
    #                        NEVER be overwritten by machine translation
    #   in_db_codes        — languages already present in the DB, regardless
    #                        of origin; --overwrite toggles whether to skip
    #                        these
    all_langs = pack.languages()
    pack_seeded_codes = {l["code"] for l in all_langs if l.get("seeded_by_poc")}
    in_db_codes = {
        n["language"] for n in pack.notices()
        if n["notice_id"] == args.notice_id and int(n["version_number"]) == args.version
    }

    if args.language:
        # Explicit opt-in: generate exactly what was requested, even if seeded.
        # Useful for refreshing a specific machine-generated translation after
        # prompt tuning; the user takes responsibility for overriding seeded.
        targets = [l for l in all_langs if l["code"] in set(args.language)]
    else:
        # Default: every non-seeded language in the pack. Hand-authored bodies
        # stay — --overwrite does NOT apply to them.
        targets = [l for l in all_langs if l["code"] not in pack_seeded_codes]

    # Without --overwrite, also skip languages already present in the DB.
    if not args.overwrite:
        targets = [l for l in targets if l["code"] not in in_db_codes]

    if not targets:
        print("Nothing to generate — every target language already has a seed notice.")
        print("Use --overwrite to regenerate, or --language <code> to force a single one.")
        return 0

    print(f"Targets:  {[l['code'] for l in targets]}")
    print()

    # Existing languages in DB — for idempotency logging.
    existing = existing_language_ids(args.notice_id, args.version)
    print(f"Existing in compliance.notice_versions: {sorted(existing)}")
    print()

    failures = 0
    generated = 0
    for lang in targets:
        code = lang["code"]
        script = lang.get("script", "")
        tier = lang.get("model_support_tier", "")
        review_needed = lang.get("human_review_required", False)

        # Target-language display name for the prompt.
        # Use a short human-readable name derived from the code when no
        # explicit field exists.
        lang_name = {
            "bn-IN": "Bengali", "te-IN": "Telugu", "mr-IN": "Marathi",
            "gu-IN": "Gujarati", "kn-IN": "Kannada", "ml-IN": "Malayalam",
            "pa-IN": "Punjabi", "hi-IN": "Hindi", "ta-IN": "Tamil",
            "en-IN": "English (India)", "ur-IN": "Urdu",
        }.get(code, code)

        system_prompt, user_prompt = build_translation_prompt(
            source_text=seed["notice_text"],
            target_language=lang_name,
            target_script=script,
        )

        print(f"[{code}] {lang_name} ({script}, tier={tier})")
        if args.dry_run:
            print(f"  system: {system_prompt[:120]}...")
            print(f"  user  : {user_prompt[:120]}...")
            continue

        try:
            translation = invoke_model(endpoint, system_prompt, user_prompt)
        except RuntimeError as e:
            print(f"  ✗ model call failed: {e}")
            failures += 1
            continue

        body = watermark + translation
        if review_needed:
            body = "[human-review required — low-resource language]\n" + body

        row = {
            "notice_version_id": f"nv_{args.notice_id}_v{args.version}_{code}",
            "notice_id": args.notice_id,
            "version_number": args.version,
            "language": code,
            "legal_basis": seed["legal_basis"],
            "notice_text": body,
            "purposes_covered": seed["purposes_covered"],
            "effective_from": seed["effective_from"],
            "effective_to": seed.get("effective_to"),
            "approved_by": seed.get("approved_by"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            upsert_notice(row)
            print(f"  ✓ merged {row['notice_version_id']} — {len(body)} chars")
            generated += 1
        except RuntimeError as e:
            print(f"  ✗ upsert failed: {e}")
            failures += 1

    print()
    print(f"Generated: {generated}   failed: {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
