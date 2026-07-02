import pytest

from app.models import Incident, IncidentStatus, TimelineEventType
from app.state_machine import InvalidTransitionError, record_error, transition


def test_transition_advances_status_and_writes_timeline(session):
    incident = Incident(fault_scenario_id="checkout-n-plus-one")
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
    incident = Incident(fault_scenario_id="checkout-n-plus-one", status=IncidentStatus.analyzing)
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


def test_transition_rejects_invalid_jump(session):
    incident = Incident(fault_scenario_id="checkout-n-plus-one", status=IncidentStatus.firing)
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
    incident = Incident(fault_scenario_id="checkout-n-plus-one", status=IncidentStatus.briefed)
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


def test_record_error_sets_message_without_changing_status(session):
    incident = Incident(fault_scenario_id="checkout-n-plus-one", status=IncidentStatus.analyzing)
    session.add(incident)
    session.commit()

    updated = record_error(session, incident, "boom")

    assert updated.status == IncidentStatus.analyzing
    assert updated.error_message == "boom"
