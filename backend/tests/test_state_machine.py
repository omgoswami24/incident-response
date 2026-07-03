import pytest

from app.models import Incident, IncidentStatus, TimelineEventType
from app.state_machine import InvalidTransitionError, record_error, transition


def test_transition_advances_status_and_writes_timeline(session):
    incident = Incident(detected_alert_text="alert")
    session.add(incident)
    session.commit()

    updated = transition(
        session,
        incident,
        IncidentStatus.analyzing,
        TimelineEventType.analyzing_started,
        "Analyzing",
    )

    assert updated.status == IncidentStatus.analyzing


def test_transition_same_status_only_writes_timeline(session):
    incident = Incident(detected_alert_text="alert", status=IncidentStatus.analyzing)
    session.add(incident)
    session.commit()

    updated = transition(
        session,
        incident,
        IncidentStatus.analyzing,
        TimelineEventType.commit_identified,
        "Commit identified",
    )

    assert updated.status == IncidentStatus.analyzing


def test_briefed_allows_remediation_and_manual_resolve(session):
    for target in (IncidentStatus.remediating, IncidentStatus.resolved):
        incident = Incident(detected_alert_text="alert", status=IncidentStatus.briefed)
        session.add(incident)
        session.commit()

        updated = transition(
            session,
            incident,
            target,
            TimelineEventType.remediation_started,
            "Next step",
        )
        assert updated.status == target


def test_remediating_resolves(session):
    incident = Incident(detected_alert_text="alert", status=IncidentStatus.remediating)
    session.add(incident)
    session.commit()

    updated = transition(
        session,
        incident,
        IncidentStatus.resolved,
        TimelineEventType.recovery_verified,
        "Recovered",
    )
    assert updated.status == IncidentStatus.resolved


def test_transition_rejects_invalid_jump(session):
    incident = Incident(detected_alert_text="alert", status=IncidentStatus.firing)
    session.add(incident)
    session.commit()

    with pytest.raises(InvalidTransitionError):
        transition(
            session,
            incident,
            IncidentStatus.resolved,
            TimelineEventType.resolved,
            "Resolved",
        )


def test_transition_rejects_going_backwards(session):
    incident = Incident(detected_alert_text="alert", status=IncidentStatus.briefed)
    session.add(incident)
    session.commit()

    with pytest.raises(InvalidTransitionError):
        transition(
            session,
            incident,
            IncidentStatus.analyzing,
            TimelineEventType.analyzing_started,
            "Analyzing",
        )


def test_any_open_state_can_be_closed_but_terminal_cannot(session):
    for status in (
        IncidentStatus.firing,
        IncidentStatus.analyzing,
        IncidentStatus.briefed,
        IncidentStatus.remediating,
        IncidentStatus.resolved,
    ):
        incident = Incident(detected_alert_text="alert", status=status)
        session.add(incident)
        session.commit()
        updated = transition(
            session, incident, IncidentStatus.closed, TimelineEventType.closed, "Closed"
        )
        assert updated.status == IncidentStatus.closed

    incident = Incident(
        detected_alert_text="alert", status=IncidentStatus.postmortem_generated
    )
    session.add(incident)
    session.commit()
    with pytest.raises(InvalidTransitionError):
        transition(
            session, incident, IncidentStatus.closed, TimelineEventType.closed, "Closed"
        )


def test_record_error_sets_message_without_changing_status(session):
    incident = Incident(detected_alert_text="alert", status=IncidentStatus.analyzing)
    session.add(incident)
    session.commit()

    updated = record_error(session, incident, "boom")

    assert updated.status == IncidentStatus.analyzing
    assert updated.error_message == "boom"
