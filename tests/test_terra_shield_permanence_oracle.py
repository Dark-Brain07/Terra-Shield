import json
import re
import sys
import pytest
from datetime import datetime, timezone
import gltest

CONTRACT_PATH = "contracts/terra_shield_permanence_oracle.py"


def build_verra_body(
    slug="bigcoast-forest-climate-initiative",
    post_id=105,
    project_name="BigCoast Forest Climate Project",
    event_type="clean",
    monitor_year=2023,
    post_date=None,
):
    content_map = {
        "clean": f"<p>{project_name} assessment for {monitor_year} indicates no reversal.</p>",
        "likely_loss": f"<p>{project_name} in {monitor_year} suffered possible wildfire damage awaiting quantification (likely loss).</p>",
        "confirmed_reversal": f"<p>{project_name} {monitor_year} carbon loss confirmed reversal report.</p>",
        "ambiguous": f"<p>{project_name} had an inconclusive update for {monitor_year}.</p>",
    }
    return json.dumps([
        {
            "id": post_id,
            "date": post_date if post_date is not None else f"{monitor_year}-07-31T12:00:00",
            "slug": slug,
            "title": {"rendered": f"{project_name} Update"},
            "content": {"rendered": content_map.get(event_type, content_map["clean"])},
        }
    ]).encode("utf-8")


def build_wfs_body(number_matched=0):
    return json.dumps({
        "type": "FeatureCollection",
        "features": [] if number_matched == 0 else [{"type": "Feature", "properties": {}}],
        "numberMatched": number_matched,
        "numberReturned": 0 if number_matched == 0 else 1,
    }).encode("utf-8")


def build_registry_body(registry_project_id="3018", project_name="BigCoast Forest Climate Project", province="BC"):
    return (
        f"VERIFIED CARBON STANDARD PROGRAM (VCS) {registry_project_id} "
        f"{project_name} {registry_project_id} Overview Country Canada State/Province {province}"
    )


def register_valid(
    contract,
    direct_vm,
    registry_project_id="3018",
    project_name="BigCoast Forest Climate Project",
    min_lon_e6=-128000000,
    min_lat_e6=50000000,
    max_lon_e6=-125000000,
    max_lat_e6=52000000,
    first_monitor_year=2023,
):
    direct_vm.mock_web(
        f"^https://registry\\.verra\\.org/verra/public/program/VCS/projects/{registry_project_id}$",
        {"status": 200, "body": build_registry_body(registry_project_id, project_name)},
    )
    return contract.register_project(
        registry_project_id,
        project_name,
        min_lon_e6,
        min_lat_e6,
        max_lon_e6,
        max_lat_e6,
        first_monitor_year,
    )


class TestRegistration:
    def test_valid_registration_and_initial_unassessed_state(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        assert key.startswith("VCS:3018:")
        perm = contract.read_permanence(key)
        assert perm["exists"] is True
        assert perm["status"] == "UNASSESSED"
        assert perm["latest_epoch"] == 0
        assert perm["next_monitor_year"] == 2023
        assert contract.can_use_as_healthy_backing(key) is False

    def test_duplicate_configuration_rejected(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        register_valid(contract, direct_vm)
        with pytest.raises(Exception):
            contract.register_project(
                "3018",
                "BigCoast Forest Climate Project",
                -128000000,
                50000000,
                -125000000,
                52000000,
                2023,
            )

    def test_registry_identity_mismatch_cannot_squat_valid_configuration(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        direct_vm.mock_web(
            "^https://registry\\.verra\\.org/verra/public/program/VCS/projects/3018$",
            {"status": 200, "body": build_registry_body("3018", "BigCoast Forest Climate Initiative")},
        )

        with pytest.raises(Exception):
            contract.register_project(
                "3018", "Unrelated Forest Project", -128000000, 50000000, -125000000, 52000000, 2023
            )

        valid_key = contract.register_project(
            "3018", "BigCoast Forest Climate Initiative", -128000000, 50000000, -125000000, 52000000, 2023
        )
        second_window_key = contract.register_project(
            "3018", "BigCoast Forest Climate Initiative", -129000000, 50000000, -126000000, 52000000, 2023
        )
        assert valid_key != second_window_key
        assert contract.read_permanence(valid_key)["status"] == "UNASSESSED"

    def test_registry_non_bc_project_rejected(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        direct_vm.mock_web(
            "^https://registry\\.verra\\.org/verra/public/program/VCS/projects/3018$",
            {"status": 200, "body": build_registry_body("3018", "BigCoast Forest Climate Project", "AB")},
        )
        with pytest.raises(Exception):
            contract.register_project(
                "3018", "BigCoast Forest Climate Project", -128000000, 50000000, -125000000, 52000000, 2023
            )

    def test_registry_identity_validator_one_variable_differentials(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        register_valid(contract, direct_vm)

        identical = {
            "registry_project_id": "3018",
            "project_name": "BigCoast Forest Climate Project",
            "registry_province": "BC",
        }
        assert direct_vm.run_validator(leader_result=identical) is True

        id_diff = dict(identical, registry_project_id="3019")
        assert direct_vm.run_validator(leader_result=id_diff) is False

        name_diff = dict(identical, project_name="Unrelated Forest Project")
        assert direct_vm.run_validator(leader_result=name_diff) is False

        province_diff = dict(identical, registry_province="AB")
        assert direct_vm.run_validator(leader_result=province_diff) is False

    def test_registry_render_configuration_locked(self, direct_deploy, direct_vm, monkeypatch):
        contract = direct_deploy(CONTRACT_PATH)
        calls = []
        runtime_gl = sys.modules["genlayer.gl"]
        actual_render = runtime_gl.nondet.web.render

        def recording_render(url, *args, **kwargs):
            calls.append((url, args, kwargs))
            return actual_render(url, *args, **kwargs)

        monkeypatch.setattr(runtime_gl.nondet.web, "render", recording_render)
        register_valid(contract, direct_vm)

        expected = (
            "https://registry.verra.org/verra/public/program/VCS/projects/3018",
            (),
            {"mode": "text", "wait_after_loaded": "10s"},
        )
        assert calls == [expected]
        assert direct_vm.run_validator() is True
        assert calls == [expected, expected]

    def test_invalid_and_oversized_project_id(self, direct_deploy):
        contract = direct_deploy(CONTRACT_PATH)
        with pytest.raises(Exception):
            contract.register_project("", "Valid Project Name", -128000000, 50000000, -125000000, 52000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("VCS3018", "Valid Project Name", -128000000, 50000000, -125000000, 52000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("12345678901", "Valid Project Name", -128000000, 50000000, -125000000, 52000000, 2023)

    def test_invalid_and_oversized_project_name(self, direct_deploy):
        contract = direct_deploy(CONTRACT_PATH)
        with pytest.raises(Exception):
            contract.register_project("3018", "Abcd", -128000000, 50000000, -125000000, 52000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("3018", "A" * 121, -128000000, 50000000, -125000000, 52000000, 2023)

    def test_non_ascii_and_whitespace_invalid_name(self, direct_deploy):
        contract = direct_deploy(CONTRACT_PATH)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project \u2601", -128000000, 50000000, -125000000, 52000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("3018", " BigCoast Forest Project", -128000000, 50000000, -125000000, 52000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project ", -128000000, 50000000, -125000000, 52000000, 2023)

    def test_reversed_out_of_bc_and_oversized_bbox(self, direct_deploy):
        contract = direct_deploy(CONTRACT_PATH)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project", -125000000, 50000000, -128000000, 52000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project", -128000000, 52000000, -125000000, 50000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project", -140000000, 50000000, -125000000, 52000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project", -128000000, 50000000, -125000000, 61000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project", -135000000, 50000000, -127000000, 52000000, 2023)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project", -128000000, 50000000, -125000000, 56000000, 2023)

    def test_invalid_current_and_future_first_year(self, direct_deploy):
        contract = direct_deploy(CONTRACT_PATH)
        current_year = datetime.now(timezone.utc).year
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project", -128000000, 50000000, -125000000, 52000000, 1989)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project", -128000000, 50000000, -125000000, 52000000, current_year)
        with pytest.raises(Exception):
            contract.register_project("3018", "BigCoast Forest Project", -128000000, 50000000, -125000000, 52000000, current_year + 1)


class TestURLAndSecurity:
    def test_hostile_verra_slugs_rejected(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)

        hostile_slugs = [
            "",
            "UPPERCASE-SLUG",
            "double--hyphen",
            "-leading-hyphen",
            "trailing-hyphen-",
            "slug/with/slash",
            "slug\\backslash",
            "../dot-dot-traversal",
            "slug:with:colon",
            "slug%20percent",
            "slug?query=1",
            "slug#fragment",
            "slug with spaces",
            "slug-\u00e9-unicode",
        ]
        for hostile_slug in hostile_slugs:
            with pytest.raises(Exception):
                contract.monitor_project(key, hostile_slug)

    def test_canonical_json_prompt_boundary_with_hostile_printable_ascii(self, direct_deploy, direct_vm):
        direct_vm.strict_mocks = True
        direct_vm.check_pickling = True
        contract = direct_deploy(CONTRACT_PATH)
        hostile_name = 'BigCoast {"injected": true} Project'
        key = register_valid(contract, direct_vm, project_name=hostile_name)
        verra_slug = "bigcoast-forest-climate-initiative"
        excerpt = f"{hostile_name} Update {hostile_name} assessment for 2023 indicates no reversal."
        canonical_input = json.dumps(
            {
                "excerpt": excerpt,
                "monitor_year": 2023,
                "project_id": "3018",
                "project_name": hostile_name,
            },
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 105, hostile_name)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(re.escape(canonical_input), {"registry_event": "NO_REVERSAL"})

        epoch_num = contract.monitor_project(key, verra_slug)
        assert epoch_num == 1


class TestEvidenceValidationAndFailures:
    def test_verra_non_2xx_and_oversized_body(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        direct_vm.clear_mocks()
        verra_slug = "bigcoast-forest-climate-initiative"

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 500, "body": b"Server Error"})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        big_body = json.dumps([
            {
                "id": 105,
                "slug": verra_slug,
                "title": {"rendered": "BigCoast Forest Climate Project Update"},
                "content": {"rendered": "A" * 26000},
            }
        ]).encode("utf-8")
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": big_body})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

    def test_verra_malformed_json_zero_or_multiple_posts(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        direct_vm.clear_mocks()
        verra_slug = "bigcoast-forest-climate-initiative"

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": b"not json"})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": b"[]"})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        multi_body = json.dumps([
            {"id": 105, "slug": verra_slug, "title": "BigCoast Forest Climate Project", "content": "c1"},
            {"id": 106, "slug": verra_slug, "title": "BigCoast Forest Climate Project", "content": "c2"},
        ]).encode("utf-8")
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": multi_body})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

    def test_verra_post_id_u32_range_boundaries(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        direct_vm.clear_mocks()
        verra_slug = "bigcoast-forest-climate-initiative"

        # Max u32 (4294967295) works
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 4294967295)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})

        ep_num = contract.monitor_project(key, verra_slug)
        assert ep_num == 1
        assert contract.read_epoch(key, 1)["verra_post_id"] == 4294967295

        # Oversized post ID (>4294967295) fails with no write
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 4294967296)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})

        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        assert contract.read_permanence(key)["latest_epoch"] == 1
        assert contract.read_permanence(key)["next_monitor_year"] == 2024

    def test_wfs_non_2xx_oversized_body_malformed_json(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        direct_vm.clear_mocks()
        verra_slug = "bigcoast-forest-climate-initiative"

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 500, "body": b"Server Error"})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        big_wfs = json.dumps({"type": "FeatureCollection", "numberMatched": 0, "padding": "X" * 4500}).encode("utf-8")
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": big_wfs})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        malformed_bodies = [
            b"not json",
            json.dumps({"numberMatched": 1}).encode("utf-8"),
            json.dumps({"type": "FeatureCollection", "numberMatched": 1, "numberReturned": 0, "features": []}).encode("utf-8"),
            json.dumps({"type": "FeatureCollection", "numberMatched": 1, "numberReturned": 1, "features": [{"type": "NotFeature"}]}).encode("utf-8"),
        ]
        for malformed_body in malformed_bodies:
            direct_vm.clear_mocks()
            direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug)})
            direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": malformed_body})
            direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
            with pytest.raises(Exception):
                contract.monitor_project(key, verra_slug)

        assert contract.read_permanence(key)["latest_epoch"] == 0

    def test_llm_malformed_non_dict_missing_extra_key_and_unknown_enum(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        direct_vm.clear_mocks()
        verra_slug = "bigcoast-forest-climate-initiative"

        # String output rejected
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", "NO_REVERSAL")
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        # Missing key
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        # Extra key in LLM output
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL", "confidence": 0.99})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        # Unknown enum value
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "PARTIAL_REVERSAL"})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

    def test_external_failure_causes_no_write(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        direct_vm.clear_mocks()
        verra_slug = "bigcoast-forest-climate-initiative"

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 500, "body": b"Error"})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        perm = contract.read_permanence(key)
        assert perm["status"] == "UNASSESSED"
        assert perm["latest_epoch"] == 0
        assert perm["next_monitor_year"] == 2023
        with pytest.raises(Exception):
            contract.read_epoch(key, 1)

    def test_wrong_year_irrelevant_and_insufficient_evidence_cause_no_write(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        direct_vm.clear_mocks()
        verra_slug = "bigcoast-forest-climate-initiative"

        evidence_cases = [
            (build_verra_body(verra_slug, monitor_year=2022), {"registry_event": "NO_REVERSAL"}),
            (build_verra_body(verra_slug, project_name="Unrelated Forest Project"), {"registry_event": "NO_REVERSAL"}),
            (build_verra_body(verra_slug, event_type="ambiguous"), {"registry_event": "INSUFFICIENT_EVIDENCE"}),
        ]
        for verra_body, llm_result in evidence_cases:
            direct_vm.clear_mocks()
            direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": verra_body})
            direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
            direct_vm.mock_llm(".*", llm_result)
            with pytest.raises(Exception):
                contract.monitor_project(key, verra_slug)
            permanence = contract.read_permanence(key)
            assert permanence["status"] == "UNASSESSED"
            assert permanence["latest_epoch"] == 0
            assert permanence["next_monitor_year"] == 2023

    def test_malformed_same_year_dates_cause_no_write(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        verra_slug = "bigcoast-forest-climate-initiative"

        for malformed_date in (
            "2023-99-99T12:00:00",
            "2023-07-31Tgarbage",
            "2023-07-31T12:00:00junk",
        ):
            direct_vm.clear_mocks()
            direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, post_date=malformed_date)})
            direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
            direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
            with pytest.raises(Exception):
                contract.monitor_project(key, verra_slug)

            permanence = contract.read_permanence(key)
            assert permanence["status"] == "UNASSESSED"
            assert permanence["latest_epoch"] == 0
            assert permanence["next_monitor_year"] == 2023


class TestConsensusAndDifferentials:
    def test_real_validator_one_variable_differentials(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        direct_vm.clear_mocks()
        verra_slug = "bigcoast-forest-climate-initiative"

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})

        # Run monitor_project to capture validator
        contract.monitor_project(key, verra_slug)

        # a. Identical tuple => True
        identical_res = {"verra_post_id": 105, "hazard_present": False, "registry_event": "NO_REVERSAL"}
        assert direct_vm.run_validator(leader_result=identical_res) is True

        # b. Only verra_post_id differs => False
        post_id_diff = {"verra_post_id": 106, "hazard_present": False, "registry_event": "NO_REVERSAL"}
        assert direct_vm.run_validator(leader_result=post_id_diff) is False

        # c. Only hazard_present differs => False
        hazard_diff = {"verra_post_id": 105, "hazard_present": True, "registry_event": "NO_REVERSAL"}
        assert direct_vm.run_validator(leader_result=hazard_diff) is False

        # d. Only registry_event differs => False
        event_diff = {"verra_post_id": 105, "hazard_present": False, "registry_event": "LIKELY_LOSS"}
        assert direct_vm.run_validator(leader_result=event_diff) is False

    def test_real_validator_malformed_calldata_rejections(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        direct_vm.clear_mocks()
        verra_slug = "bigcoast-forest-climate-initiative"

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})

        contract.monitor_project(key, verra_slug)

        # Wrong calldata type (string instead of dict)
        assert direct_vm.run_validator(leader_result="not return") is False

        # Wrong calldata type (list instead of dict)
        assert direct_vm.run_validator(leader_result=[105, False, "NO_REVERSAL"]) is False

        # Missing key
        missing_key = {"verra_post_id": 105, "hazard_present": False}
        assert direct_vm.run_validator(leader_result=missing_key) is False

        # Extra key
        extra_key = {"verra_post_id": 105, "hazard_present": False, "registry_event": "NO_REVERSAL", "extra": 1}
        assert direct_vm.run_validator(leader_result=extra_key) is False

        # Invalid field types / values
        bad_post_id_str = {"verra_post_id": "105", "hazard_present": False, "registry_event": "NO_REVERSAL"}
        assert direct_vm.run_validator(leader_result=bad_post_id_str) is False

        bad_post_id_neg = {"verra_post_id": -1, "hazard_present": False, "registry_event": "NO_REVERSAL"}
        assert direct_vm.run_validator(leader_result=bad_post_id_neg) is False

        bad_post_id_oversized = {"verra_post_id": 4294967296, "hazard_present": False, "registry_event": "NO_REVERSAL"}
        assert direct_vm.run_validator(leader_result=bad_post_id_oversized) is False

        # Leader error simulated
        assert direct_vm.run_validator(leader_error=Exception("Leader failed")) is False

    def test_strict_mocks_and_pickling_checks(self, direct_deploy, direct_vm):
        direct_vm.strict_mocks = True
        direct_vm.check_pickling = True
        contract = direct_deploy(CONTRACT_PATH)
        key = register_valid(contract, direct_vm)
        verra_slug = "bigcoast-forest-climate-initiative"
        expected_wfs_url = (
            "https://openmaps.gov.bc.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE.PROT_HISTORICAL_FIRE_POLYS_SP/ows?"
            "service=WFS&version=2.0.0&request=GetFeature&"
            "typeNames=pub%3AWHSE_LAND_AND_NATURAL_RESOURCE.PROT_HISTORICAL_FIRE_POLYS_SP&"
            "outputFormat=application%2Fjson&"
            "propertyName=FIRE_NUMBER%2CFIRE_YEAR%2CFIRE_SIZE_HECTARES%2CFIRE_DATE&"
            "sortBy=FIRE_NUMBER&count=1&"
            "CQL_FILTER=FIRE_YEAR%3D2023+AND+BBOX%28SHAPE%2C-128.000000%2C50.000000%2C-125.000000%2C52.000000%2C%27EPSG%3A4326%27%29"
        )

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=bigcoast-forest-climate-initiative&_fields=id,date,slug,link,title,content$", {"status": 200, "body": build_verra_body(verra_slug)})
        direct_vm.mock_web(f"^{re.escape(expected_wfs_url)}$", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})

        epoch_num = contract.monitor_project(key, verra_slug)
        assert epoch_num == 1


class TestLifecycleAndTransitions:
    def test_full_transition_table(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        verra_slug = "bigcoast-forest-climate-initiative"

        # Case 1: UNASSESSED + CLEAN -> HEALTHY
        key1 = register_valid(contract, direct_vm, "1001", "BigCoast Forest Climate Project 1")
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 101, "BigCoast Forest Climate Project 1", "clean")})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        contract.monitor_project(key1, verra_slug)
        assert contract.read_permanence(key1)["status"] == "HEALTHY"

        # Case 2: UNASSESSED + WATCH -> WATCH
        key2 = register_valid(contract, direct_vm, "1002", "BigCoast Forest Climate Project 2")
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 102, "BigCoast Forest Climate Project 2", "clean")})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(1)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        contract.monitor_project(key2, verra_slug)
        assert contract.read_permanence(key2)["status"] == "WATCH"

        # Case 3: UNASSESSED + REVERSAL -> REVERSED
        key3 = register_valid(contract, direct_vm, "1003", "BigCoast Forest Climate Project 3")
        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 103, "BigCoast Forest Climate Project 3", "confirmed_reversal")})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "CONFIRMED_REVERSAL"})
        contract.monitor_project(key3, verra_slug)
        assert contract.read_permanence(key3)["status"] == "REVERSED"

    def test_sticky_watch_remains_watch_after_clean(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        verra_slug = "bigcoast-forest-climate-initiative"
        key = register_valid(contract, direct_vm, "2001")

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 201, "BigCoast Forest Climate Project", "likely_loss")})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "LIKELY_LOSS"})
        contract.monitor_project(key, verra_slug)
        assert contract.read_permanence(key)["status"] == "WATCH"

        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 202, "BigCoast Forest Climate Project", "clean", 2024)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        contract.monitor_project(key, verra_slug)
        assert contract.read_permanence(key)["status"] == "WATCH"

    def test_sticky_reversed_remains_reversed_after_all_outcomes(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        verra_slug = "bigcoast-forest-climate-initiative"
        key = register_valid(contract, direct_vm, "3001")

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 301, "BigCoast Forest Climate Project", "confirmed_reversal")})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "CONFIRMED_REVERSAL"})
        contract.monitor_project(key, verra_slug)
        assert contract.read_permanence(key)["status"] == "REVERSED"

        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 302, "BigCoast Forest Climate Project", "clean", 2024)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        contract.monitor_project(key, verra_slug)
        assert contract.read_permanence(key)["status"] == "REVERSED"

    def test_sequential_years_only(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        verra_slug = "bigcoast-forest-climate-initiative"
        key = register_valid(contract, direct_vm, "4001")

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 401)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        contract.monitor_project(key, verra_slug)

        ep1 = contract.read_epoch(key, 1)
        assert ep1["monitor_year"] == 2023
        assert contract.read_permanence(key)["next_monitor_year"] == 2024

        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 402, monitor_year=2024)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        contract.monitor_project(key, verra_slug)

        ep2 = contract.read_epoch(key, 2)
        assert ep2["monitor_year"] == 2024
        assert contract.read_permanence(key)["next_monitor_year"] == 2025

    def test_current_year_monitoring_rejected_without_state_change(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        current_year = datetime.now(timezone.utc).year
        completed_year = current_year - 1
        verra_slug = "bigcoast-forest-climate-initiative"
        key = register_valid(contract, direct_vm, "5001", first_monitor_year=completed_year)

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 501, monitor_year=completed_year)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        contract.monitor_project(key, verra_slug)

        before = contract.read_permanence(key)
        assert before["latest_epoch"] == 1
        assert before["next_monitor_year"] == current_year

        direct_vm.clear_mocks()
        with pytest.raises(Exception):
            contract.monitor_project(key, verra_slug)

        assert contract.read_permanence(key) == before

    def test_historical_epoch_immutability(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        verra_slug = "bigcoast-forest-climate-initiative"
        key = register_valid(contract, direct_vm, "6001")

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 601)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        contract.monitor_project(key, verra_slug)

        ep1 = contract.read_epoch(key, 1)

        direct_vm.clear_mocks()
        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 602, "BigCoast Forest Climate Project", "likely_loss", 2024)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "LIKELY_LOSS"})
        contract.monitor_project(key, verra_slug)

        ep1_after = contract.read_epoch(key, 1)
        assert ep1 == ep1_after

    def test_read_views_and_healthy_backing_always_match_stored_state(self, direct_deploy, direct_vm):
        contract = direct_deploy(CONTRACT_PATH)
        verra_slug = "bigcoast-forest-climate-initiative"
        key = register_valid(contract, direct_vm, "7001")

        assert contract.can_use_as_healthy_backing(key) is False
        assert contract.read_permanence(key)["status"] == "UNASSESSED"

        direct_vm.mock_web("^https://verra\\.org/wp-json/wp/v2/verra-views\\?slug=.*", {"status": 200, "body": build_verra_body(verra_slug, 701)})
        direct_vm.mock_web("^https://openmaps\\.gov\\.bc\\.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE\\.PROT_HISTORICAL_FIRE_POLYS_SP/ows\\?.*", {"status": 200, "body": build_wfs_body(0)})
        direct_vm.mock_llm(".*", {"registry_event": "NO_REVERSAL"})
        contract.monitor_project(key, verra_slug)

        assert contract.can_use_as_healthy_backing(key) is True
        assert contract.read_permanence(key)["status"] == "HEALTHY"
        latest = contract.read_latest_epoch(key)
        assert latest["epoch_number"] == 1
        assert latest["resulting_status"] == "HEALTHY"
