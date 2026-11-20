from app.domain.enums import Provider
from app.providers.intervals.budget import INTERVALS_BUDGET_POLICY
from app.providers.intervals.definition import INTERVALS, is_configured
from app.providers.intervals.importer import IntervalsImporter
from app.providers.intervals.oauth import IntervalsOAuth
from app.providers.intervals.syncer import IntervalsSyncer
from app.providers.intervals.webhook import IntervalsWebhookParser
from tests.helpers import configure_intervals


def test_is_configured_requires_both_the_client_id_and_secret(monkeypatch):
    configure_intervals(monkeypatch, client_id="", client_secret="")
    assert is_configured() is False

    configure_intervals(monkeypatch, client_id="client-id", client_secret="")
    assert is_configured() is False

    configure_intervals(monkeypatch, client_id="client-id", client_secret="client-secret")
    assert is_configured() is True


def test_the_definition_wires_oauth_importer_syncer_budget_and_webhook():
    assert INTERVALS.provider == Provider.INTERVALS
    assert isinstance(INTERVALS.oauth, IntervalsOAuth)
    assert INTERVALS.token_refresher is None
    assert INTERVALS.importer is IntervalsImporter
    assert INTERVALS.syncer is IntervalsSyncer
    assert INTERVALS.budget_policy is INTERVALS_BUDGET_POLICY
    assert isinstance(INTERVALS.webhook, IntervalsWebhookParser)
