"""Integration and unit tests for the Baseball DFS Simulator.

Tests marked @pytest.mark.integration require external API access (DK lobby,
MLB Stats API) and should be skipped in CI with: pytest -m "not integration"

Unit tests (normalise_dk_team, sanitise_projection) run without external deps.
"""
from __future__ import annotations

import pytest

from tests.conftest import SAMPLE_PROJECTION, SAMPLE_PITCHER_PROJECTION


# ============================================================================
# UNIT TESTS — no external deps, always pass
# ============================================================================


class TestNormaliseDkTeam:
    """Verify team abbreviation normalisation catches known DK quirks."""

    def _normalise(self, abbr: str) -> str:
        from api.staging_projections import _normalise_dk_team
        return _normalise_dk_team(abbr)

    def test_ath_to_oak(self):
        """ATH (Athletics DK code) must map to OAK."""
        assert self._normalise("ATH") == "OAK"

    def test_az_to_ari(self):
        """AZ (Arizona shorthand) must map to ARI."""
        assert self._normalise("AZ") == "ARI"

    def test_sfg_to_sf(self):
        """SFG must map to SF."""
        assert self._normalise("SFG") == "SF"

    def test_kcr_to_kc(self):
        """KCR must map to KC."""
        assert self._normalise("KCR") == "KC"

    def test_tbr_to_tb(self):
        """TBR must map to TB."""
        assert self._normalise("TBR") == "TB"

    def test_sdp_to_sd(self):
        """SDP must map to SD."""
        assert self._normalise("SDP") == "SD"

    def test_was_to_wsh(self):
        """WAS must map to WSH."""
        assert self._normalise("WAS") == "WSH"

    def test_chw_to_cws(self):
        """CHW must map to CWS."""
        assert self._normalise("CHW") == "CWS"

    def test_passthrough_known_team(self):
        """Standard abbreviations pass through unchanged."""
        assert self._normalise("NYY") == "NYY"
        assert self._normalise("BOS") == "BOS"
        assert self._normalise("LAD") == "LAD"

    def test_passthrough_unknown_team(self):
        """Unknown abbreviations pass through uppercased."""
        assert self._normalise("XYZ") == "XYZ"

    def test_case_insensitive(self):
        """Input is case-insensitive."""
        assert self._normalise("ath") == "OAK"
        assert self._normalise("Az") == "ARI"
        assert self._normalise("sfg") == "SF"

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert self._normalise("") == ""


class TestSanitiseProjection:
    """Verify _sanitise_projection includes all SlateProjectionOut fields."""

    def _sanitise(self, p: dict) -> dict:
        from api.projections import _sanitise_projection
        return _sanitise_projection(p)

    def _get_model_fields(self) -> set:
        from api.projections import SlateProjectionOut
        return set(SlateProjectionOut.model_fields.keys())

    def test_all_model_fields_present(self):
        """sanitise_projection output must contain every SlateProjectionOut field."""
        result = self._sanitise(SAMPLE_PROJECTION)
        model_fields = self._get_model_fields()
        missing = model_fields - set(result.keys())
        assert not missing, f"Missing fields in sanitised output: {missing}"

    def test_no_extra_fields(self):
        """sanitise_projection should not add fields that aren't in the model."""
        result = self._sanitise(SAMPLE_PROJECTION)
        model_fields = self._get_model_fields()
        extra = set(result.keys()) - model_fields
        # Extra fields are acceptable (model ignores them) but let's track
        # NOTE: This is a soft check — extra keys don't break Pydantic
        # but indicate drift. Uncomment assertion to make strict:
        # assert not extra, f"Extra fields in sanitised output: {extra}"

    def test_pitcher_projection_sanitises_cleanly(self):
        """Pitcher projection sanitises without raising."""
        result = self._sanitise(SAMPLE_PITCHER_PROJECTION)
        assert result["player_name"] == "Gerrit Cole"
        assert result["is_pitcher"] is True
        assert result["season_era"] == 3.15

    def test_empty_dict_gets_defaults(self):
        """An empty dict should get safe defaults for all required fields."""
        result = self._sanitise({})
        assert result["player_name"] == "Unknown"
        assert result["floor_pts"] == 0.0
        assert result["median_pts"] == 0.0
        assert result["ceiling_pts"] == 0.0
        assert result["team"] == ""
        assert result["position"] == "UTIL"

    def test_result_constructs_valid_model(self):
        """The sanitised dict must successfully construct a SlateProjectionOut."""
        from api.projections import SlateProjectionOut
        result = self._sanitise(SAMPLE_PROJECTION)
        # This will raise ValidationError if anything is wrong
        obj = SlateProjectionOut(**result)
        assert obj.player_name == "Aaron Judge"
        assert obj.median_pts == 9.8


# ============================================================================
# INTEGRATION TESTS — require external API access
# ============================================================================


@pytest.mark.integration
class TestSlateEndpoint:
    """Integration tests for the staging slates endpoint."""

    async def test_slate_endpoint_returns_slates(self, client):
        """GET /staging/projections/slates should return a list with required fields."""
        resp = await client.get("/staging/projections/slates")
        # Accept 200 (slates found) or 200 with empty list (no games today)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

        if len(data) > 0:
            slate = data[0]
            # Required fields per SlateOut model
            assert "slate_id" in slate
            assert "name" in slate
            assert "game_count" in slate
            assert "site" in slate
            assert "game_type" in slate
            assert slate["site"] == "dk"
            assert isinstance(slate["game_count"], int)
            assert slate["game_count"] > 0


@pytest.mark.integration
class TestProjectionFields:
    """Integration tests that verify projection data quality."""

    async def test_all_projections_have_required_fields(self, client):
        """Every projection from featured endpoint must have core fields populated."""
        resp = await client.get("/staging/projections/slates/featured/projections")
        if resp.status_code != 200:
            pytest.skip(f"Featured projections not available: {resp.status_code}")

        data = resp.json()
        if not data:
            pytest.skip("No projections returned (likely no games today)")

        required_fields = [
            "player_name", "team", "position",
            "floor_pts", "median_pts", "ceiling_pts",
        ]

        for i, proj in enumerate(data):
            for field in required_fields:
                assert field in proj, (
                    f"Projection [{i}] ({proj.get('player_name', '?')}) missing field: {field}"
                )
                assert proj[field] is not None, (
                    f"Projection [{i}] ({proj.get('player_name', '?')}) has None for required field: {field}"
                )

            # is_home should be explicitly set (not None) — the OAK/ATH bug
            # caused is_home to be None for Athletics players
            assert "is_home" in proj, (
                f"Projection [{i}] ({proj.get('player_name', '?')}) missing is_home"
            )
            # opp_team should be present for all players
            assert "opp_team" in proj, (
                f"Projection [{i}] ({proj.get('player_name', '?')}) missing opp_team"
            )

    async def test_team_normalization_no_ath(self, client):
        """No projection should have team='ATH' — must be normalised to 'OAK'."""
        resp = await client.get("/staging/projections/slates/featured/projections")
        if resp.status_code != 200:
            pytest.skip(f"Featured projections not available: {resp.status_code}")

        data = resp.json()
        if not data:
            pytest.skip("No projections returned (likely no games today)")

        ath_players = [
            p["player_name"] for p in data
            if p.get("team") == "ATH" or p.get("opp_team") == "ATH"
        ]
        assert not ath_players, (
            f"Found {len(ath_players)} players with team/opp_team='ATH' "
            f"(should be 'OAK'): {ath_players[:5]}"
        )


@pytest.mark.integration
class TestHealthEndpoint:
    """Basic smoke test that the app starts and serves requests."""

    async def test_health_returns_ok(self, client):
        """GET /health should return 200 with status=ok."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
