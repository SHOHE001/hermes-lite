#!/usr/bin/env python3
"""Approach B: raw HTTP probe for Computer Use API via Claude Max OAuth.

Issue #10 research code. NOT for production import. CLI / credential schema
dependent. Re-evaluate before reuse. See ../README.md.

Usage:
  python3 computer_use_probe.py approach-b
      Run live probe against api.anthropic.com (reads ~/.claude/.credentials.json).
  python3 computer_use_probe.py approach-b --apply-console-confirm <enum> --checked-at <iso8601>
      After live probe stdout JSON, post-process to attach console confirmation.
      <enum> = incremented_subscription | incremented_extra_usage | no_change | unknown
  python3 computer_use_probe.py --classify-fixture <path>
      Classify a stored fixture (no network). Returns allowlist JSON.

All output JSON uses only B-5 allowlist fields. Raw bodies, tokens, account_id,
request_id, Authorization header, cookie, /home/shohei are never printed.
"""
import json
import os
import sys
import time
import argparse
import urllib.request
import urllib.error

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
COMPUTER_USE_BETA = "computer-use-2025-01-24"
DEFAULT_MODEL = "claude-sonnet-4-5"
CONSOLE_WINDOW_MIN = 15
TIMEOUT_SEC = 60

# Short non-sensitive probe prompt (intentionally English, generic)
PROBE_PROMPT = "Take a screenshot of the desktop and describe what you see in one line."

ALLOWLIST_FIELDS = {
    "approach", "status", "outcome", "sub_outcome", "redacted_error_type",
    "error_code", "message_class", "usage_token_counts", "billing_observation",
    "billing_delta_class", "console_checked_at", "console_window_minutes",
    "model_used", "stop_reason", "tool_use_observed", "additional_turn_attempted",
    "elapsed_seconds", "stage", "cli_help_has_betas_flag",
    "cli_probe_tool_use_observed", "exit_code", "notes",
}


def emit(record):
    """Validate against allowlist and print as JSON."""
    extra = set(record.keys()) - ALLOWLIST_FIELDS
    if extra:
        # internal contract violation: print a minimal error JSON and exit
        sys.stderr.write(f"allowlist violation: {sorted(extra)}\n")
        json.dump({
            "approach": "B", "outcome": "undetermined",
            "sub_outcome": "probe_input_error", "exit_code": 4,
            "notes": "internal: allowlist violation"
        }, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(4)
    json.dump(record, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")


def normalize_message_class(msg):
    if not msg:
        return "other"
    m = msg.lower()
    if "permission" in m:
        return "permission"
    if "computer use is not available" in m or "not available" in m:
        return "not_available"
    if "invalid" in m or "malformed" in m or "model not found" in m:
        return "invalid_request"
    return "other"


def classify_response(status, error_type, error_message, tool_use_observed,
                      stop_reason):
    """Return (outcome, sub_outcome) per B-2-a truth table."""
    if status == 200:
        if tool_use_observed:
            return "conditional", "tool_use_observed_but_billing_unknown"
        return "conditional", "messages_api_only"
    if status == 400:
        if error_type == "invalid_request_error":
            if error_message and "computer use is not available" in error_message.lower():
                return "unsupported", "beta_not_allowed"
            return "undetermined", "probe_input_error"
        return "undetermined", "probe_input_error"
    if status == 401:
        return "undetermined", "auth_failure"
    if status == 403:
        if error_type == "permission_error":
            return "unsupported", "api_explicit_reject_after_auth"
        return "undetermined", "auth_failure"
    if status == 429:
        return "undetermined", "rate_limited"
    if status is None or (isinstance(status, int) and 500 <= status < 600) or status == 408:
        return "undetermined", "timeout"
    return "undetermined", "network_error"


def apply_console_confirmation(record, delta_class, checked_at):
    """B-2-c: merge console confirmation into a classified record."""
    if record["outcome"] not in ("conditional",):
        # supported / unsupported / undetermined are not affected
        return record
    sub = record["sub_outcome"]
    record["billing_delta_class"] = delta_class
    record["console_checked_at"] = checked_at
    if sub == "tool_use_observed_but_billing_unknown":
        if delta_class == "incremented_subscription":
            record["outcome"] = "supported"
            record["sub_outcome"] = "tool_use_observed_and_subscription_billing"
            record["billing_observation"] = "subscription_billing"
        elif delta_class == "incremented_extra_usage":
            record["sub_outcome"] = "extra_usage_billing"
            record["billing_observation"] = "extra_usage_billing"
        else:
            record["billing_observation"] = "console_confirmation_required"
    elif sub == "messages_api_only":
        if delta_class == "incremented_subscription":
            record["billing_observation"] = "subscription_billing"
        elif delta_class == "incremented_extra_usage":
            record["billing_observation"] = "extra_usage_billing"
        else:
            record["billing_observation"] = "console_confirmation_required"
    return record


def read_credentials():
    """B-1: schema-tolerant credential read with categorized error emission."""
    path = os.path.expanduser("~/.claude/.credentials.json")
    if not os.path.exists(path):
        emit({
            "approach": "B", "outcome": "undetermined",
            "sub_outcome": "credential_missing", "exit_code": 1,
            "stage": "approach_b_credential",
            "notes": "credentials.json absent",
        })
        sys.exit(1)
    try:
        with open(path) as f:
            cred = json.loads(f.read())
    except json.JSONDecodeError:
        emit({
            "approach": "B", "outcome": "undetermined",
            "sub_outcome": "credential_schema_unknown", "exit_code": 1,
            "stage": "approach_b_credential",
            "notes": "credentials.json parse failure",
        })
        sys.exit(1)

    # B-1: try known credential schemas in order. Known containers list MUST stay
    # in sync with plan.md.
    known_containers = {"oauthAccount", "access_token", "token", "claudeAiOauth"}
    token = None
    if isinstance(cred.get("oauthAccount"), dict):
        token = cred["oauthAccount"].get("access_token")
    if not token:
        token = cred.get("access_token") or cred.get("token")
    if not token and isinstance(cred.get("claudeAiOauth"), dict):
        token = cred["claudeAiOauth"].get("accessToken")
    if not token:
        seen = sorted(cred.keys()) if isinstance(cred, dict) else []
        # Distinguish: known container present (schema changed/missing field)
        # vs no known container at all (entirely new schema). Both map to
        # credential_schema_unknown but the notes fingerprint helps re-eval.
        if set(seen) & known_containers:
            note = f"known_container_no_token top_keys_fingerprint={seen}"
        else:
            note = f"unknown_schema top_keys_fingerprint={seen}"
        emit({
            "approach": "B", "outcome": "undetermined",
            "sub_outcome": "credential_schema_unknown", "exit_code": 1,
            "stage": "approach_b_credential",
            "notes": note[:80],
        })
        sys.exit(1)
    return token


def build_probe_body(model):
    return {
        "model": model,
        "max_tokens": 1024,
        "tools": [
            {
                "type": "computer_20250124",
                "name": "computer",
                "display_width_px": 1280,
                "display_height_px": 800,
                "display_number": 1,
            }
        ],
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
    }


def do_request(token, model):
    """One POST to the Anthropic Messages API. Returns (status, parsed_body, elapsed)."""
    body = json.dumps(build_probe_body(model)).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-version": ANTHROPIC_VERSION,
            "anthropic-beta": COMPUTER_USE_BETA,
            "content-type": "application/json",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else None, time.time() - t0
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return e.code, parsed, time.time() - t0
    except (urllib.error.URLError, TimeoutError) as e:
        return None, {"_synthetic_error": "timeout_or_network", "_kind": type(e).__name__}, time.time() - t0


def extract_response_features(status, body):
    """Pull tool_use, stop_reason, error.type, error.message, usage."""
    tool_use = False
    stop_reason = None
    error_type = None
    error_message = None
    error_code = None
    usage = {}
    if isinstance(body, dict):
        if status == 200:
            stop_reason = body.get("stop_reason")
            for blk in body.get("content", []) or []:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    tool_use = True
                    break
            u = body.get("usage") or {}
            usage = {
                "input": u.get("input_tokens", 0),
                "output": u.get("output_tokens", 0),
                "cache_creation": u.get("cache_creation_input_tokens", 0),
                "cache_read": u.get("cache_read_input_tokens", 0),
            }
        elif body.get("error"):
            err = body["error"]
            error_type = err.get("type")
            error_message = err.get("message")
            error_code = err.get("code")
    return tool_use, stop_reason, error_type, error_message, error_code, usage


def base_record(approach, outcome, sub_outcome, **extra):
    rec = {
        "approach": approach,
        "outcome": outcome,
        "sub_outcome": sub_outcome,
        "additional_turn_attempted": False,
        "console_window_minutes": CONSOLE_WINDOW_MIN,
        "console_checked_at": None,
        "billing_delta_class": "not_applicable",
        "billing_observation": "not_applicable",
        "exit_code": 0,
    }
    rec.update(extra)
    return rec


def run_approach_b():
    token = read_credentials()
    model = DEFAULT_MODEL
    status, body, elapsed = do_request(token, model)
    tool_use, stop_reason, etype, emsg, ecode, usage = extract_response_features(status, body)
    outcome, sub = classify_response(status, etype, emsg, tool_use, stop_reason)
    msg_class = normalize_message_class(emsg)

    rec = base_record(
        approach="B",
        outcome=outcome,
        sub_outcome=sub,
        status=status,
        model_used=model,
        stop_reason=stop_reason,
        tool_use_observed=tool_use,
        usage_token_counts=usage if status == 200 else {},
        elapsed_seconds=int(elapsed),
        stage="approach_b_request",
    )
    if etype:
        rec["redacted_error_type"] = etype
        rec["message_class"] = msg_class
        if ecode is not None:
            rec["error_code"] = ecode
    if outcome == "conditional":
        rec["billing_observation"] = "console_confirmation_required"
        rec["billing_delta_class"] = "unknown"
    if outcome == "undetermined" and sub in ("timeout", "network_error"):
        rec["exit_code"] = 3
    emit(rec)


def run_classify_fixture(path):
    with open(path) as f:
        fx = json.load(f)
    status = fx.get("status")
    body = fx.get("body")
    tool_use, stop_reason, etype, emsg, ecode, usage = extract_response_features(status, body)
    outcome, sub = classify_response(status, etype, emsg, tool_use, stop_reason)
    msg_class = normalize_message_class(emsg)

    rec = base_record(
        approach="B",
        outcome=outcome,
        sub_outcome=sub,
        status=status,
        model_used=DEFAULT_MODEL,
        stop_reason=stop_reason,
        tool_use_observed=tool_use,
        usage_token_counts=usage if status == 200 else {},
        elapsed_seconds=0,
        stage="approach_b_request",
    )
    if etype is not None:
        rec["redacted_error_type"] = etype
        rec["message_class"] = msg_class
        if ecode is not None:
            rec["error_code"] = ecode
    if outcome == "conditional":
        rec["billing_observation"] = "console_confirmation_required"
        rec["billing_delta_class"] = "unknown"
    emit(rec)


def run_apply_console(delta_class, checked_at):
    raw = sys.stdin.read().strip()
    rec = json.loads(raw)
    rec = apply_console_confirmation(rec, delta_class, checked_at)
    emit(rec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default=None,
                    help="approach-b | (omitted with --classify-fixture)")
    ap.add_argument("--classify-fixture", help="Fixture JSON path")
    ap.add_argument("--apply-console-confirm",
                    choices=["incremented_subscription", "incremented_extra_usage",
                             "no_change", "unknown"],
                    help="Post-process stdin JSON with console confirmation")
    ap.add_argument("--checked-at", default=None,
                    help="ISO 8601 UTC timestamp for console_checked_at")
    args = ap.parse_args()

    if args.classify_fixture:
        run_classify_fixture(args.classify_fixture)
        return
    if args.apply_console_confirm:
        run_apply_console(args.apply_console_confirm, args.checked_at)
        return
    if args.mode == "approach-b":
        run_approach_b()
        return
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
