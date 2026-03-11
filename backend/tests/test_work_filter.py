"""
test_work_filter.py — 50-example test suite for WorkFilter.

Tests the fast-path (rule-based) classification only.
Claude calls are tested separately via integration tests.
"""
import pytest
from unittest.mock import AsyncMock, patch

# Adjust sys.path so we can import from backend root
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.ingestion.work_filter import WorkFilter, Label


@pytest.fixture
def wf():
    with patch("core.ingestion.work_filter.get_settings") as mock_settings:
        mock_settings.return_value.anthropic_api_key = "test"
        mock_settings.return_value.claude_model = "claude-sonnet-4-5"
        return WorkFilter()


# ── Email: work ────────────────────────────────────────────────────────────────

def test_email_work_domain_workday(wf):
    r = wf._classify_email({"sender": "hr@workday.com", "subject": "Benefits enrollment", "snippet": ""})
    assert r.label == Label.WORK

def test_email_work_domain_salesforce(wf):
    r = wf._classify_email({"sender": "no-reply@salesforce.com", "subject": "Your Salesforce report", "snippet": ""})
    assert r.label == Label.WORK

def test_email_work_domain_jira(wf):
    r = wf._classify_email({"sender": "atlassian@jira.com", "subject": "Sprint review ticket", "snippet": ""})
    assert r.label == Label.WORK

def test_email_noreply_sender(wf):
    r = wf._classify_email({"sender": "noreply@company.com", "subject": "Update", "snippet": ""})
    assert r.label == Label.WORK

def test_email_donotreply_sender(wf):
    r = wf._classify_email({"sender": "donotreply@payroll.co", "subject": "Payslip", "snippet": ""})
    assert r.label == Label.WORK

def test_email_work_subject_jira(wf):
    r = wf._classify_email({"sender": "team@company.com", "subject": "jira ticket updated", "snippet": ""})
    assert r.label == Label.WORK

def test_email_work_subject_pull_request(wf):
    r = wf._classify_email({"sender": "github@company.com", "subject": "github pr needs review", "snippet": ""})
    assert r.label == Label.WORK

def test_email_work_subject_expense_report(wf):
    r = wf._classify_email({"sender": "finance@corp.com", "subject": "expense report due", "snippet": ""})
    assert r.label == Label.WORK

def test_email_work_subject_invoice(wf):
    r = wf._classify_email({"sender": "billing@vendor.com", "subject": "invoice #12345", "snippet": ""})
    assert r.label == Label.WORK

def test_email_work_domain_hubspot(wf):
    r = wf._classify_email({"sender": "notify@hubspot.com", "subject": "Deal stage changed", "snippet": ""})
    assert r.label == Label.WORK


# ── Email: personal ────────────────────────────────────────────────────────────

def test_email_personal_birthday(wf):
    r = wf._classify_email({"sender": "alice@gmail.com", "subject": "Birthday party Saturday!", "snippet": ""})
    assert r.label == Label.PERSONAL

def test_email_personal_anniversary(wf):
    r = wf._classify_email({"sender": "restaurant@gmail.com", "subject": "Anniversary dinner reservation", "snippet": ""})
    assert r.label == Label.PERSONAL

def test_email_personal_flight_confirmation(wf):
    r = wf._classify_email({"sender": "airlines@travel.com", "subject": "Flight confirmation to Lisbon", "snippet": ""})
    assert r.label == Label.PERSONAL

def test_email_personal_your_order(wf):
    r = wf._classify_email({"sender": "store@amazon.com", "subject": "your order has shipped", "snippet": ""})
    assert r.label == Label.PERSONAL

def test_email_personal_wedding(wf):
    r = wf._classify_email({"sender": "sarah@gmail.com", "subject": "Wedding invitation!", "snippet": ""})
    assert r.label == Label.PERSONAL


# ── Calendar: work ─────────────────────────────────────────────────────────────

def test_calendar_work_standup(wf):
    r = wf._classify_calendar({"title": "Daily standup", "calendar_name": "personal", "attendees": []})
    assert r.label == Label.WORK

def test_calendar_work_sprint_retro(wf):
    r = wf._classify_calendar({"title": "Sprint retro Q3", "calendar_name": "", "attendees": []})
    assert r.label == Label.WORK

def test_calendar_work_1on1(wf):
    r = wf._classify_calendar({"title": "1:1 with manager", "calendar_name": "", "attendees": ["manager@co.com"]})
    assert r.label == Label.WORK

def test_calendar_work_interview(wf):
    r = wf._classify_calendar({"title": "Candidate interview — backend", "calendar_name": "", "attendees": []})
    assert r.label == Label.WORK

def test_calendar_work_all_hands(wf):
    r = wf._classify_calendar({"title": "All hands meeting", "calendar_name": "", "attendees": []})
    assert r.label == Label.WORK

def test_calendar_work_okr(wf):
    r = wf._classify_calendar({"title": "Q4 OKR planning session", "calendar_name": "", "attendees": []})
    assert r.label == Label.WORK

def test_calendar_work_calendar_name(wf):
    r = wf._classify_calendar({"title": "Strategy sync", "calendar_name": "Work", "attendees": []})
    assert r.label == Label.WORK

def test_calendar_work_performance_review(wf):
    r = wf._classify_calendar({"title": "Annual performance review", "calendar_name": "", "attendees": []})
    assert r.label == Label.WORK


# ── Calendar: personal ─────────────────────────────────────────────────────────

def test_calendar_personal_dinner(wf):
    r = wf._classify_calendar({"title": "Dinner with Alice", "calendar_name": "Home", "attendees": []})
    assert r.label == Label.PERSONAL

def test_calendar_personal_birthday(wf):
    r = wf._classify_calendar({"title": "Mom's birthday", "calendar_name": "", "attendees": []})
    assert r.label == Label.PERSONAL

def test_calendar_personal_gym(wf):
    r = wf._classify_calendar({"title": "Gym — leg day", "calendar_name": "", "attendees": []})
    assert r.label == Label.PERSONAL

def test_calendar_personal_therapist(wf):
    r = wf._classify_calendar({"title": "Therapist appointment", "calendar_name": "", "attendees": []})
    assert r.label == Label.PERSONAL

def test_calendar_personal_vacation(wf):
    r = wf._classify_calendar({"title": "Portugal vacation", "calendar_name": "Personal", "attendees": []})
    assert r.label == Label.PERSONAL

def test_calendar_personal_concert(wf):
    r = wf._classify_calendar({"title": "Concert — The National", "calendar_name": "", "attendees": []})
    assert r.label == Label.PERSONAL


# ── Calendar: ambiguous (large meetings) ─────────────────────────────────────

def test_calendar_ambiguous_large_meeting(wf):
    r = wf._classify_calendar({"title": "Planning session", "calendar_name": "", "attendees": list(range(10))})
    assert r.label == Label.AMBIGUOUS


# ── iMessage / WhatsApp ───────────────────────────────────────────────────────

def test_message_work_jira(wf):
    r = wf._classify_message({"sender_name": "Dev", "text_snippet": "Can you look at the JIRA ticket for the deploy?", "group_name": ""})
    assert r.label == Label.WORK

def test_message_work_sprint(wf):
    r = wf._classify_message({"sender_name": "PM", "text_snippet": "Sprint review is tomorrow at 3pm", "group_name": ""})
    assert r.label == Label.WORK

def test_message_work_lgtm(wf):
    r = wf._classify_message({"sender_name": "Engineer", "text_snippet": "LGTM, approving the PR now", "group_name": ""})
    assert r.label == Label.WORK

def test_message_work_group_name_team(wf):
    r = wf._classify_message({"sender_name": "Bob", "text_snippet": "Good morning!", "group_name": "Backend team"})
    assert r.label == Label.WORK

def test_message_work_deployment(wf):
    r = wf._classify_message({"sender_name": "Alice", "text_snippet": "deployment failed on staging, rolling back", "group_name": ""})
    assert r.label == Label.WORK

def test_message_work_google_meet(wf):
    r = wf._classify_message({"sender_name": "Manager", "text_snippet": "google meet link for our sync: meet.google.com/abc", "group_name": ""})
    assert r.label == Label.WORK


# ── Maps ─────────────────────────────────────────────────────────────────────

def test_maps_personal_restaurant(wf):
    r = wf._classify_maps({"place_name": "Bix Restaurant", "address": "56 Gold St, SF", "duration_minutes": 90})
    assert r.label == Label.PERSONAL

def test_maps_personal_gym(wf):
    r = wf._classify_maps({"place_name": "Equinox Gym", "address": "Main St", "duration_minutes": 60})
    assert r.label == Label.PERSONAL

def test_maps_personal_cafe(wf):
    r = wf._classify_maps({"place_name": "Blue Bottle Coffee cafe", "address": "Mission St", "duration_minutes": 45})
    assert r.label == Label.PERSONAL

def test_maps_personal_museum(wf):
    r = wf._classify_maps({"place_name": "SFMOMA museum", "address": "Third St", "duration_minutes": 120})
    assert r.label == Label.PERSONAL


# ── FilterResult.passes ───────────────────────────────────────────────────────

def test_filter_result_personal_passes(wf):
    r = wf._classify_email({"sender": "friend@gmail.com", "subject": "Birthday party Saturday!", "snippet": ""})
    assert r.passes is True

def test_filter_result_work_does_not_pass(wf):
    r = wf._classify_email({"sender": "hr@workday.com", "subject": "Enrollment", "snippet": ""})
    assert r.passes is False

def test_filter_result_ambiguous_does_not_pass(wf):
    r = wf._classify_calendar({"title": "Team planning", "calendar_name": "", "attendees": list(range(11))})
    assert r.passes is False


# ── build_safe_preview ────────────────────────────────────────────────────────

def test_safe_preview_format(wf):
    preview = wf.build_safe_preview("email", {"sender": "work@co.com"})
    assert "email" in preview
    assert "work" in preview
    assert "1" in preview


# ── Unknown content type returns None from fast_path ─────────────────────────

def test_unknown_type_returns_none(wf):
    result = wf._fast_path("reddit", {"text": "hello"})
    assert result is None
