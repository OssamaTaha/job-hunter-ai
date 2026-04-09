import os
import json
from datetime import datetime
from pymongo import MongoClient, ASCENDING, DESCENDING

mongo_client = None
db = None


def get_db():
    global mongo_client, db
    if db is not None:
        return db
    try:
        mongo_url = os.environ.get("DATABASE_URL", "mongodb://localhost:27017")
        mongo_client = MongoClient(mongo_url)
        db = mongo_client["jobhunter"]
        _ensure_indexes()
        print("Connected to MongoDB")
        return db
    except Exception as e:
        print(f"MongoDB connection failed: {e}")
        return None


def _ensure_indexes():
    if db is None:
        return
    db.users.create_index("username", unique=True)
    db.entries.create_index([("userId", ASCENDING), ("jobId", ASCENDING)], unique=True)
    db.jobs.create_index([("query", ASCENDING), ("location_search", ASCENDING)])
    db.vault.create_index([("userId", ASCENDING), ("account", ASCENDING), ("folder", ASCENDING), ("uid", ASCENDING)], unique=True)
    db.config.create_index([("userId", ASCENDING), ("key", ASCENDING)], unique=True)
    db.profiles.create_index("userId", unique=True)
    db.mailbox_meta.create_index([("userId", ASCENDING), ("account", ASCENDING), ("folder", ASCENDING)], unique=True)


# --- Users ---
def create_user(user_id: str, username: str, hashed_password: str):
    get_db().users.insert_one({"id": user_id, "username": username, "password": hashed_password})


def get_user_by_username(username: str):
    return get_db().users.find_one({"username": username})


def get_user_by_id(user_id: str):
    return get_db().users.find_one({"id": user_id})


# --- Config ---
def get_config(user_id: str) -> dict:
    docs = get_db().config.find({"userId": user_id})
    return {doc["key"]: doc["value"] for doc in docs}


def set_config(user_id: str, key: str, value: str):
    get_db().config.update_one(
        {"userId": user_id, "key": key},
        {"$set": {"userId": user_id, "key": key, "value": value}},
        upsert=True
    )


def delete_config(user_id: str, key: str):
    get_db().config.delete_one({"userId": user_id, "key": key})


def get_accounts(user_id: str) -> list:
    cfg = get_config(user_id)
    accounts = []
    for key, value in cfg.items():
        if key.startswith("account:"):
            email = key.split(":", 1)[1]
            try:
                data = json.loads(value)
                accounts.append({"email": email, **data})
            except Exception:
                accounts.append({"email": email, "pass": value, "enabled": True})
    return accounts


# --- Profiles ---
def get_profile(user_id: str):
    return get_db().profiles.find_one({"userId": user_id})


def save_profile(user_id: str, profile: dict, cv_yaml: str = ""):
    get_db().profiles.update_one(
        {"userId": user_id},
        {"$set": {
            "userId": user_id,
            "profile_json": json.dumps(profile) if isinstance(profile, dict) else profile,
            "cv_yaml": cv_yaml,
            "updated_at": datetime.now().isoformat()
        }},
        upsert=True
    )


# --- Entries (Job Tracker) ---
def get_entries(user_id: str) -> list:
    docs = get_db().entries.find({"userId": user_id}).sort("updated_at", DESCENDING)
    result = []
    for doc in docs:
        doc.pop("_id", None)
        result.append(doc)
    return result


def update_entry(user_id: str, job_id: str, data: dict):
    now = datetime.now().isoformat()
    existing = get_db().entries.find_one({"userId": user_id, "jobId": job_id})
    if existing:
        existing_data = existing.get("data_json", {})
        if isinstance(existing_data, str):
            existing_data = json.loads(existing_data)
        existing_data.update(data.get("data_json", data))
        get_db().entries.update_one(
            {"userId": user_id, "jobId": job_id},
            {"$set": {
                "status": data.get("status", existing.get("status", "applied")),
                "appliedAt": data.get("appliedAt", existing.get("appliedAt", now)),
                "data_json": existing_data,
                "updated_at": now
            }}
        )
    else:
        get_db().entries.insert_one({
            "userId": user_id,
            "jobId": job_id,
            "status": data.get("status", "applied"),
            "appliedAt": data.get("appliedAt", now),
            "data_json": data.get("data_json", data),
            "created_at": now,
            "updated_at": now
        })


def delete_entry(user_id: str, job_id: str):
    get_db().entries.delete_one({"userId": user_id, "jobId": job_id})


# --- Vault (Emails) ---
def save_vault_messages(user_id: str, messages: list):
    if not messages:
        return
    for msg in messages:
        msg["userId"] = user_id
        msg["created_at"] = msg.get("created_at", datetime.now().isoformat())
        msg["updated_at"] = datetime.now().isoformat()
    try:
        get_db().vault.insert_many(messages, ordered=False)
    except Exception:
        for msg in messages:
            try:
                get_db().vault.update_one(
                    {"userId": user_id, "account": msg.get("account"), "folder": msg.get("folder"), "uid": msg.get("uid")},
                    {"$set": msg},
                    upsert=True
                )
            except Exception:
                pass


def get_vault(user_id: str, limit: int = 100, folder: str = None) -> list:
    query = {"userId": user_id}
    if folder:
        query["folder"] = folder
    docs = get_db().vault.find(query).sort("date", DESCENDING).limit(limit)
    result = []
    seen = set()
    for doc in docs:
        key = f"{doc.get('subject', '')}|{doc.get('date', '')}|{doc.get('from_address', '')}"
        if key in seen:
            continue
        seen.add(key)
        doc.pop("_id", None)
        result.append(doc)
    return result


# --- Mailbox Meta ---
def get_mailbox_meta(user_id: str, account: str, folder: str):
    return get_db().mailbox_meta.find_one({"userId": user_id, "account": account, "folder": folder})


def update_mailbox_meta(user_id: str, account: str, folder: str, data: dict):
    get_db().mailbox_meta.update_one(
        {"userId": user_id, "account": account, "folder": folder},
        {"$set": {**data, "userId": user_id, "account": account, "folder": folder}},
        upsert=True
    )


# --- Cached Jobs ---
def cache_jobs(jobs: list, query: str, location: str):
    if not jobs:
        return
    now = datetime.now().isoformat()
    docs = []
    for j in jobs:
        doc = j if isinstance(j, dict) else j.__dict__
        docs.append({**doc, "query": query.lower(), "location_search": location.lower(), "timestamp": now})
    try:
        get_db().jobs.insert_many(docs, ordered=False)
    except Exception:
        pass


def get_cached_jobs(query: str, location: str, limit: int = 30) -> list:
    d = get_db()
    if d is None:
        return []
    # Only return results less than 30 minutes old
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(minutes=30)).isoformat()
    docs = d.jobs.find(
        {"query": query.lower(), "location_search": location.lower(), "timestamp": {"$gte": cutoff}}
    ).sort("timestamp", DESCENDING).limit(limit)
    result = []
    for doc in docs:
        doc.pop("_id", None)
        result.append(doc)
    return result
