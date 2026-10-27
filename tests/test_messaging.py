"""WhatsApp + SMS: chat flow, linking, photo diagnosis, alerts, webhook. No network: sends are simulated."""
import asyncio
import hashlib
import hmac
import json

from app.core.channel_store import get_channel_store
from app.core.config import get_settings
from app.core.twin_store import get_twin_store
from app.services import channels, chat_flow, disease_models
from app.services import twin_engine as te

PROMPT = "আমার ৩০ শতাংশ জমি আছে, গত ৪ বছর ধান চাষ করেছি, এখন ভুট্টা চাষ করতে চাই।"
JPEG = b"\xff\xd8\xff" + b"0" * 200


def run(coro):
    return asyncio.run(coro)


def say(phone, text, channel="whatsapp", **kw):
    return run(chat_flow.process_inbound({"phone": phone, "channel": channel, "type": "text", "text": text, **kw}))


def number_of(phone, slot, value):
    """Option number (as typed by the farmer) of `value` in the question currently asked."""
    rec = run(get_channel_store().get_link(phone))
    q = rec["queue"][0]
    assert q["slot"] == slot
    return str([o["value"] for o in q["options"]].index(value) + 1)


def test_normalize_phone():
    assert channels.normalize_phone("8801712345678") == "01712345678"
    assert channels.normalize_phone("+8801712345678") == "01712345678"
    assert channels.normalize_phone("01712345678") == "01712345678"
    assert channels.normalize_phone("14155551234") is None
    assert channels.normalize_phone("") is None


def test_advisor_flow_on_whatsapp():
    ph = "01711000001"
    r = say(ph, PROMPT)
    assert len(r) == 1 and "১." in r[0]                       # first question, numbered options
    r = say(ph, number_of(ph, "season", "rabi"))
    assert "সেচ" in r[0]                                      # next question (one at a time)
    r = say(ph, number_of(ph, "irrigation", "good"))
    assert "ভুট্টা" in r[0] and "পরামর্শ" in r[0]             # final advice
    assert run(get_channel_store().get_link(ph))["queue"] == []


def test_sms_is_short_and_has_no_photo():
    ph = "01711000002"
    say(ph, PROMPT, "sms")
    say(ph, number_of(ph, "season", "rabi"), "sms")
    r = say(ph, number_of(ph, "irrigation", "good"), "sms")
    assert "ভুট্টা" in r[0] and len(r[0]) <= get_settings().sms_max_chars
    img = run(chat_flow.process_inbound({"phone": ph, "channel": "sms", "type": "image", "media_id": "x"}))
    assert "WhatsApp" in img[0]


def test_unclear_answer_asks_again():
    ph = "01711000003"
    say(ph, PROMPT)
    r = say(ph, "xyz কিছু একটা")
    assert "বুঝতে পারিনি" in r[0] and len(r) == 2


def test_duplicate_webhook_message_is_answered_once():
    ph = "01711000004"
    assert say(ph, PROMPT, id="wamid.1")
    assert say(ph, PROMPT, id="wamid.1") == []


def test_help_and_reset():
    ph = "01711000005"
    assert "স্বাগতম" in say(ph, "hi")[0]
    say(ph, PROMPT)
    assert "নতুন" in say(ph, "শুরু")[0]
    assert run(get_channel_store().get_link(ph))["queue"] == []


def test_link_code_is_single_use_and_whatsapp_only():
    store, ph = get_channel_store(), "01711000006"
    code = run(store.create_code("user-a"))
    assert "WhatsApp" in say(ph, f"LINK {code}", "sms")[0]    # SMS cannot link
    assert "সংযুক্ত হয়েছে" in say(ph, f"link {code}")[0]
    assert run(store.get_link(ph))["user_id"] == "user-a"
    assert "সঠিক নয়" in say("01711000007", f"LINK {code}")[0]   # already used
    assert "সঠিক নয়" in say("01711000007", "LINK 000000")[0]


def test_relinking_moves_the_account_to_the_new_phone():
    store = get_channel_store()
    say("01711000008", f"LINK {run(store.create_code('user-m'))}")
    say("01711000009", f"LINK {run(store.create_code('user-m'))}")
    assert run(store.get_link("01711000008")) is None
    assert run(store.get_link_by_user("user-m"))["phone"] == "01711000009"


def test_stop_and_start_alerts():
    ph = "01711000010"
    say(ph, "বন্ধ")
    assert run(get_channel_store().get_link(ph))["alerts"] is False
    say(ph, "START")
    assert run(get_channel_store().get_link(ph))["alerts"] is True


def _photo(ph, caption="", img=JPEG):
    async def fake(_media_id, max_bytes=2_000_000):
        return img
    old, channels.wa_download_media = channels.wa_download_media, fake
    try:
        return run(chat_flow.process_inbound({"phone": ph, "channel": "whatsapp", "type": "image",
                                              "media_id": "m1", "caption": caption}))
    finally:
        channels.wa_download_media = old


def test_photo_needs_a_linked_account():
    assert "LINK" in _photo("01711000011")[0]


def test_photo_diagnosis_for_linked_farmer():
    store, ph = get_channel_store(), "01711000012"
    say(ph, f"LINK {run(store.create_code('user-p'))}")
    assert "চলমান প্লট নেই" in _photo(ph)[0]                  # linked but no plot yet
    plot = te.new_plot("user-p", "আমার ধান", "aman", "doash", 33, seed=3, start_date="2026-07-10")
    run(get_twin_store().save_plot(plot))
    disease_models.register("aman", lambda b: ("blast", "ব্লাস্ট", 0.95, False))
    try:
        out = _photo(ph, caption="আমার ধান")[0]
    finally:
        disease_models.unregister("aman")
    assert "আমার ধান" in out and "ব্লাস্ট" in out and "সংরক্ষণ করা হয় না" in out
    assert "ছোট হতে হবে" in _photo(ph, img=b"not an image")[0]
    assert "নামানো যায়নি" in _photo(ph, img=None)[0]


def test_alerts_pushed_to_whatsapp_only_when_linked_and_enabled():
    store = get_channel_store()
    plot = te.new_plot("user-q", "প্লট", "aman", "doash", 33, seed=3, start_date="2026-07-10")
    ev = [{"day": 5, "kind": "alert", "payload": {"level": "critical", "title_bn": "সেচ দিন", "text_bn": "মাটি শুকনো"}},
          {"day": 5, "kind": "alert", "payload": {"level": "info", "title_bn": "তথ্য", "text_bn": "x"}}]
    assert run(chat_flow.push_alerts(plot, ev)) == []                    # not linked
    say("01711000013", f"LINK {run(store.create_code('user-q'))}")
    out = run(chat_flow.push_alerts(plot, ev))
    assert len(out) == 1 and out[0]["kind"] == "whatsapp" and out[0]["payload"]["status"] == "simulated"
    assert out[0]["payload"]["to"] == "0171****13"                      # phone is masked
    say("01711000013", "বন্ধ")
    assert run(chat_flow.push_alerts(plot, ev)) == []                    # opted out


def test_alert_outside_24h_window_needs_template():
    assert channels.within_24h(None) is False
    s = get_settings()
    old = (s.whatsapp_access_token, s.whatsapp_phone_number_id, s.whatsapp_alert_template)
    s.whatsapp_access_token, s.whatsapp_phone_number_id, s.whatsapp_alert_template = "t", "1", ""
    try:
        assert run(channels.wa_send_alert("01711000014", "x", None)) == "needs_template"
    finally:
        s.whatsapp_access_token, s.whatsapp_phone_number_id, s.whatsapp_alert_template = old


def test_signature_check():
    s, body = get_settings(), b'{"a":1}'
    old = s.whatsapp_app_secret
    s.whatsapp_app_secret = "topsecret"
    try:
        good = "sha256=" + hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
        assert channels.verify_signature(body, good)
        assert not channels.verify_signature(body, "sha256=00")
        assert not channels.verify_signature(body, None)
    finally:
        s.whatsapp_app_secret = old


def test_fit_words_never_cuts_mid_word():
    t = channels.fit_words("আমার জমিতে ধান চাষ করা ভালো হবে না কারণ পানি নেই", 20)
    assert len(t) <= 20 and t.endswith("…") and " " not in t[-3:]


# ----------------------------------------------------------------------- HTTP layer
def _wa_payload(frm, **msg):
    return {"entry": [{"changes": [{"value": {"messages": [{"from": frm, "id": "wamid.X", **msg}]}}]}]}


def test_parse_whatsapp():
    from app.api.messaging import parse_whatsapp
    m = parse_whatsapp(_wa_payload("8801712345678", type="text", text={"body": "hi"}))
    assert m[0]["phone"] == "01712345678" and m[0]["type"] == "text" and m[0]["text"] == "hi"
    m = parse_whatsapp(_wa_payload("8801712345678", type="image", image={"id": "M", "caption": "c"}))
    assert m[0]["type"] == "image" and m[0]["media_id"] == "M"
    assert parse_whatsapp(_wa_payload("14155551234", type="text", text={"body": "x"})) == []   # foreign number
    assert parse_whatsapp(_wa_payload("8801712345678", type="audio"))[0]["type"] == "other"
    assert parse_whatsapp({"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]}) == []


def test_http_endpoints():
    from fastapi.testclient import TestClient
    from app.main import app
    c, s = TestClient(app), get_settings()
    old = (s.whatsapp_verify_token, s.whatsapp_app_secret, s.channel_secret)
    s.whatsapp_verify_token, s.whatsapp_app_secret, s.channel_secret = "vt", "", "sec"
    try:
        r = c.get("/messaging/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"})
        assert r.status_code == 200 and r.text == "42"
        assert c.get("/messaging/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "1"}).status_code == 403

        assert c.post("/messaging/whatsapp/webhook", json=_wa_payload("8801712345678", type="text", text={"body": "hi"})).json() == {"status": "ok"}
        s.whatsapp_app_secret = "k"
        assert c.post("/messaging/whatsapp/webhook", json={}).status_code == 403            # unsigned once a secret is set
        raw = json.dumps({"entry": []}).encode()
        sig = "sha256=" + hmac.new(b"k", raw, hashlib.sha256).hexdigest()
        assert c.post("/messaging/whatsapp/webhook", content=raw, headers={"x-hub-signature-256": sig}).status_code == 200

        assert c.post("/messaging/sms/inbound", json={"from": "01712345670", "text": "hi"}).status_code == 403
        r = c.post("/messaging/sms/inbound", json={"from": "8801712345670", "text": "hi"}, headers={"x-channel-secret": "sec"})
        assert r.status_code == 200 and r.json()["replies"]

        code = c.post("/messaging/link-code", headers={"x-dev-user": "http-user"}).json()["code"]
        assert len(code) == 6
        say("01711000020", f"LINK {code}")
        st = c.get("/messaging/status", headers={"x-dev-user": "http-user"}).json()
        assert st["linked"] is True and st["phone_masked"] == "0171****20"
        assert c.delete("/messaging/link", headers={"x-dev-user": "http-user"}).json() == {"linked": False}
        assert c.get("/messaging/status", headers={"x-dev-user": "http-user"}).json()["linked"] is False
    finally:
        s.whatsapp_verify_token, s.whatsapp_app_secret, s.channel_secret = old
