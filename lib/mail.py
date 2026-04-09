import imaplib
import email
from email.header import decode_header
import re
from datetime import datetime
from lib import db, ai, crypto

JOB_SIGNALS = re.compile(
    r"(application|interview|congratulations|offer|next steps|assessment|shortlist|"
    r"applied|position|opportunity|hiring|recruiter|talent|screening|technical test)",
    re.IGNORECASE
)
BLACKLIST = re.compile(
    r"(no-reply|newsletter|alert|notification|unsubscribe|marketing|promo|digest|update)",
    re.IGNORECASE
)


def _decode_str(val):
    if val is None:
        return ""
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", errors="replace")
        except Exception:
            return str(val)
    return str(val)


def _decode_header_val(header_val):
    if not header_val:
        return ""
    decoded_parts = decode_header(header_val)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return " ".join(result)


def _get_imap_config(email_addr: str):
    domain = email_addr.split("@")[-1].lower()
    if "gmail" in domain:
        return "imap.gmail.com", 993, {
            "sent": "[Gmail]/Sent Mail",
            "all": "[Gmail]/All Mail",
            "inbox": "INBOX"
        }
    elif "outlook" in domain or "hotmail" in domain or "live" in domain:
        return "outlook.office365.com", 993, {
            "sent": "Sent",
            "all": "INBOX",
            "inbox": "INBOX"
        }
    else:
        return f"imap.{domain}", 993, {
            "sent": "Sent",
            "all": "INBOX",
            "inbox": "INBOX"
        }


def _extract_body(msg):
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    text = payload.decode("utf-8", errors="replace")
                    break
            elif ct == "text/html" and not text:
                payload = part.get_payload(decode=True)
                if payload:
                    html = payload.decode("utf-8", errors="replace")
                    text = re.sub(r"<[^>]+>", " ", html)
                    text = re.sub(r"\s+", " ", text).strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode("utf-8", errors="replace")
    return text[:2000]


def sync_mail(user_id: str, account_email: str, account_pass: str,
              jobs: list = None, limit: int = 50, deep: bool = False,
              stats_only: bool = False, target_folder: str = None,
              user_config: dict = None) -> dict:

    host, port, folder_map = _get_imap_config(account_email)

    try:
        password = crypto.decrypt(account_pass)
    except Exception:
        password = account_pass

    try:
        imap = imaplib.IMAP4_SSL(host, port)
        imap.login(account_email, password)
    except Exception as e:
        return {"error": f"IMAP connection failed: {str(e)}", "matches": []}

    folders_to_scan = [folder_map["inbox"]]
    if not target_folder:
        folders_to_scan.append(folder_map.get("sent", "Sent"))
    else:
        folders_to_scan = [target_folder]

    matches = []
    stats = {}

    for folder in folders_to_scan:
        try:
            status, _ = imap.select(folder, readonly=True)
            if status != "OK":
                continue
        except Exception:
            continue

        # Get message count
        status, data = imap.search(None, "ALL")
        if status != "OK":
            continue
        all_uids = data[0].split()
        total = len(all_uids)

        meta = db.get_mailbox_meta(user_id, account_email, folder) or {}
        high = meta.get("high", 0)

        stats[folder] = {"total": total, "high": high}

        if stats_only:
            continue

        # Determine range to fetch
        if not all_uids:
            continue

        # Fetch newest emails first
        uids_to_fetch = all_uids[-limit:] if not deep else all_uids
        uids_to_fetch = list(reversed(uids_to_fetch))

        vault_messages = []

        for uid_bytes in uids_to_fetch[:limit]:
            uid_str = uid_bytes.decode() if isinstance(uid_bytes, bytes) else str(uid_bytes)

            try:
                status, msg_data = imap.fetch(uid_str, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
            except Exception:
                continue

            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
            if not raw:
                continue

            msg = email.message_from_bytes(raw)
            subject = _decode_header_val(msg.get("Subject", ""))
            from_raw = _decode_header_val(msg.get("From", ""))
            date_str = msg.get("Date", "")

            # Extract from address
            from_match = re.search(r"<([^>]+)>", from_raw)
            from_address = from_match.group(1) if from_match else from_raw
            from_contact = re.sub(r"\s*<[^>]+>", "", from_raw).strip().strip('"')

            # Skip blacklisted
            if BLACKLIST.search(from_raw) or BLACKLIST.search(subject):
                if not JOB_SIGNALS.search(subject):
                    continue

            # Check for job signals
            is_job_signal = bool(JOB_SIGNALS.search(subject) or JOB_SIGNALS.search(from_raw))

            # Match against tracked jobs
            matched_job = None
            if jobs:
                for job in jobs:
                    company = (job.get("company", "") or "").lower()
                    if company and len(company) > 2 and company in subject.lower() + " " + from_raw.lower():
                        matched_job = job
                        break

            body_text = ""
            ai_json = None

            if deep or is_job_signal or matched_job:
                body_text = _extract_body(msg)

                if user_config and _has_groq_key(user_config):
                    if matched_job or is_job_signal:
                        ai_json = ai.classify_email_ai(subject, body_text, user_config)
                    elif deep and not matched_job:
                        discovery = ai.discover_job_ai(subject, body_text, from_raw, user_config)
                        if discovery.get("isJob"):
                            ai_json = discovery
                            matched_job = {"company": discovery.get("company", ""), "title": discovery.get("role", "")}

            vault_msg = {
                "uid": int(uid_str),
                "folder": folder,
                "account": account_email,
                "subject": subject,
                "from_contact": from_contact,
                "from_address": from_address,
                "date": date_str,
                "text": body_text[:1000] if body_text else "",
                "snippet": body_text[:200] if body_text else subject[:200],
                "ai_json": ai_json
            }
            vault_messages.append(vault_msg)

            if matched_job or (ai_json and ai_json.get("isJob")):
                matches.append({
                    "jobId": matched_job.get("jobId", "") if matched_job else "",
                    "company": (matched_job or {}).get("company", "") or (ai_json or {}).get("company", ""),
                    "title": (matched_job or {}).get("title", "") or (ai_json or {}).get("role", ""),
                    "suggestedStatus": (ai_json or {}).get("category", "applied"),
                    "date": date_str,
                    "subject": subject
                })

        # Save to vault
        if vault_messages:
            db.save_vault_messages(user_id, vault_messages)

        # Update meta
        if all_uids:
            new_high = int(all_uids[-1].decode() if isinstance(all_uids[-1], bytes) else all_uids[-1])
            db.update_mailbox_meta(user_id, account_email, folder, {"high": new_high, "total": total})

    try:
        imap.logout()
    except Exception:
        pass

    return {
        "matches": matches,
        "stats": stats,
        "aiActive": bool(user_config and _has_groq_key(user_config))
    }


def _has_groq_key(user_config: dict) -> bool:
    return bool(user_config.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY"))


import os
