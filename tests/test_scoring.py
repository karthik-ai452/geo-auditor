"""Unit tests for the scoring engine."""

import pytest
from geo_auditor.models import ScoreComponent, Pillar, PillarScore
from geo_auditor.scoring import compute_pillar_score, compute_overall_score, build_action_plan
from geo_auditor.models import Finding, Severity


class TestComputePillarScore:
    def test_perfect_score(self):
        components = [
            ScoreComponent("check1", 50, 50, "perfect"),
            ScoreComponent("check2", 50, 50, "perfect"),
        ]
        result = compute_pillar_score(Pillar.CRAWLABILITY, components)
        assert result.score == 100.0
        assert result.pillar == Pillar.CRAWLABILITY

    def test_zero_score(self):
        components = [
            ScoreComponent("check1", 0, 50, "failed"),
            ScoreComponent("check2", 0, 50, "failed"),
        ]
        result = compute_pillar_score(Pillar.CRAWLABILITY, components)
        assert result.score == 0.0

    def test_half_score(self):
        components = [
            ScoreComponent("check1", 25, 50),
            ScoreComponent("check2", 25, 50),
        ]
        result = compute_pillar_score(Pillar.CRAWLABILITY, components)
        assert result.score == 50.0

    def test_no_components(self):
        result = compute_pillar_score(Pillar.CRAWLABILITY, [])
        assert result.score == 0.0

    def test_capped_at_100(self):
        components = [ScoreComponent("bonus", 120, 100)]
        result = compute_pillar_score(Pillar.CRAWLABILITY, components)
        assert result.score == 100.0

    def test_weight_assigned(self):
        components = [ScoreComponent("check", 50, 50)]
        result = compute_pillar_score(Pillar.CRAWLABILITY, components)
        assert result.weight == 0.20

        result2 = compute_pillar_score(Pillar.ANSWERABILITY, components)
        assert result2.weight == 0.25

        result3 = compute_pillar_score(Pillar.BRAND_RECALL, components)
        assert result3.weight == 0.35


class TestComputeOverallScore:
    def test_weighted_average(self):
        pillars = [
            PillarScore(Pillar.CRAWLABILITY, 80, 0.20),
            PillarScore(Pillar.ANSWERABILITY, 60, 0.25),
            PillarScore(Pillar.STRUCTURE, 90, 0.20),
            PillarScore(Pillar.BRAND_RECALL, 70, 0.35),
        ]
        result = compute_overall_score(pillars)
        # 80*0.20 + 60*0.25 + 90*0.20 + 70*0.35 = 16 + 15 + 18 + 24.5 = 73.5
        assert result.total == 73.5

    def test_grade_strong(self):
        pillars = [PillarScore(Pillar.CRAWLABILITY, 90, 0.20),
                   PillarScore(Pillar.ANSWERABILITY, 85, 0.25),
                   PillarScore(Pillar.STRUCTURE, 80, 0.20),
                   PillarScore(Pillar.BRAND_RECALL, 85, 0.35)]
        result = compute_overall_score(pillars)
        assert result.grade == "Strong"

    def test_grade_critical(self):
        pillars = [PillarScore(Pillar.CRAWLABILITY, 10, 0.20),
                   PillarScore(Pillar.ANSWERABILITY, 20, 0.25),
                   PillarScore(Pillar.STRUCTURE, 30, 0.20),
                   PillarScore(Pillar.BRAND_RECALL, 15, 0.35)]
        result = compute_overall_score(pillars)
        assert result.grade == "Critical"


class TestActionPlan:
    def test_sorted_by_priority(self):
        findings = [
            Finding(id="1", title="Low impact", pillar=Pillar.CRAWLABILITY,
                    severity=Severity.WARNING, impact=30, effort=80, fix="fix1"),
            Finding(id="2", title="High impact", pillar=Pillar.CRAWLABILITY,
                    severity=Severity.CRITICAL, impact=90, effort=10, fix="fix2"),
            Finding(id="3", title="Medium", pillar=Pillar.CRAWLABILITY,
                    severity=Severity.WARNING, impact=60, effort=40, fix="fix3"),
        ]
        plan = build_action_plan(findings)
        assert plan[0].id == "2"  # highest priority first
        assert plan[1].id == "3"
        assert plan[2].id == "1"

    def test_filters_positives(self):
        findings = [
            Finding(id="1", title="Good thing", pillar=Pillar.CRAWLABILITY,
                    severity=Severity.POSITIVE, impact=0, effort=0),
            Finding(id="2", title="Bad thing", pillar=Pillar.CRAWLABILITY,
                    severity=Severity.WARNING, impact=50, effort=20, fix="fix"),
        ]
        plan = build_action_plan(findings)
        assert len(plan) == 1
        assert plan[0].id == "2"

    def test_filters_no_fix(self):
        findings = [
            Finding(id="1", title="No fix", pillar=Pillar.CRAWLABILITY,
                    severity=Severity.WARNING, impact=50, effort=20, fix=""),
        ]
        plan = build_action_plan(findings)
        assert len(plan) == 0

    def test_priority_formula(self):
        """priority = impact * (1 - effort/100)"""
        f = Finding(id="test", title="test", pillar=Pillar.CRAWLABILITY,
                    severity=Severity.WARNING, impact=80, effort=20, fix="fix")
        # 80 * (1 - 20/100) = 80 * 0.8 = 64
        assert f.priority == 64.0
