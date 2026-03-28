# Multi-User Meeting Routing

## Problem

`_get_any_ref()` in `src/bot.py` returns the first stored conversation reference regardless of who organized the meeting. If multiple users have chatted with the bot, notifications can go to the wrong person.

Two layers:

1. **Graph subscription scope** — currently monitors only `ORGANIZER_TEAMS_MAIL` (single user). Meetings organized by other users are invisible to the bot.
2. **Notification routing** — even with a single organizer, if multiple people have chatted with the bot, the proactive message may go to the wrong one.

---

## Solution

### 1. Save refs keyed by email (`src/bot.py` + `src/tools/state_store.py`)

When a user sends a message, resolve their email from Graph API using their AAD object ID, then store `email → ConversationReference` in blob storage (`conv_refs_by_email.json`).

```python
# In _save_ref(), after saving by aad_object_id:
def _resolve_and_save_email_ref(aad_object_id: str, ref):
    token = _get_graph_token()  # reuse existing _graph_token() from function_app
    r = requests.get(
        f"https://graph.microsoft.com/v1.0/users/{aad_object_id}?$select=mail,userPrincipalName",
        headers={"Authorization": f"Bearer {token}"}
    )
    email = r.json().get("mail") or r.json().get("userPrincipalName")
    if email:
        save_conv_ref_for_email(email.lower(), ref)
```

### 2. Route by organizer email (`src/bot.py`)

Replace `_get_any_ref()` with `_get_ref_for_organizer(organizer_email)`:

```python
def _get_ref_for_organizer(organizer_email: str) -> ConversationReference | None:
    email = organizer_email.lower()
    # Check in-memory cache
    ref = _conv_refs_by_email.get(email)
    if ref:
        return ref
    # Load from blob
    ref_dict = load_conv_ref_for_email(email)
    if ref_dict:
        ref = _deserialize_ref(ref_dict)
        _conv_refs_by_email[email] = ref
        return ref
    return None
```

In `process_meeting_webhook`, pass `organizer_email` to this function instead of `_get_any_ref()`.

### 3. Multi-organizer subscription (`function_app.py`)

Replace single `ORGANIZER_TEAMS_MAIL` with comma-separated `ORGANIZER_EMAILS`:

```python
organizers = os.environ.get("ORGANIZER_EMAILS", os.environ.get("ORGANIZER_TEAMS_MAIL", ""))
for email in [e.strip() for e in organizers.split(",") if e.strip()]:
    uid = get_user_id(token, email)
    _create_subscription_for_user(uid, token, expiry)
```

---

## Files to change

| File | Change |
|------|--------|
| `src/tools/state_store.py` | Add `save_conv_ref_for_email()` / `load_conv_ref_for_email()` using `conv_refs_by_email.json` blob |
| `src/bot.py` | Replace `_get_any_ref()` with `_get_ref_for_organizer(email)`, update `_save_ref()` to resolve email |
| `function_app.py` | Support multiple organizers in `_renew_or_create_subscription()` and `poll_transcripts` |

## Azure permissions needed

No new license. May need admin consent for `User.Read.All` if not already granted (needed to resolve email from AAD object ID). Check in Azure Portal → App Registration → API permissions.

## Environment variable change

```
# Before
ORGANIZER_TEAMS_MAIL=user@company.com

# After (backwards compatible — single or multiple)
ORGANIZER_EMAILS=user1@company.com,user2@company.com
```
