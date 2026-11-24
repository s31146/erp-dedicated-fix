import unittest

from fastapi import HTTPException

from app import guardrail


class GuardrailTests(unittest.TestCase):
    def setUp(self):
        guardrail.reset()
        with guardrail._lock:
            guardrail._inflight_reports.clear()

    def test_tenant_id_is_parsed_from_route(self):
        self.assertEqual(guardrail.tenant_from_path("/t/12/orders"), 12)
        self.assertIsNone(guardrail.tenant_from_path("/health"))

    def test_non_positive_tenant_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            guardrail.check(0)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_small_tenant_report_limit_is_two(self):
        with guardrail.report_budget(2):
            with guardrail.report_budget(2):
                with self.assertRaises(HTTPException) as ctx:
                    with guardrail.report_budget(2):
                        self.fail("third concurrent report should be rejected")
                self.assertEqual(ctx.exception.status_code, 429)

    def test_report_slot_is_released_after_request(self):
        for _ in range(3):
            with guardrail.report_budget(3):
                pass
        self.assertEqual(guardrail.snapshot()["reports_inflight"].get(3), 0)

    def test_enterprise_tenant_has_separate_report_budget(self):
        with guardrail.report_budget(1):
            with guardrail.report_budget(1):
                with guardrail.report_budget(1):
                    pass

    def test_latency_metrics_are_recorded(self):
        guardrail.record(2, 100.0, 200)
        guardrail.record(2, 300.0, 500)
        summary = guardrail.snapshot()["small_tenants"]
        self.assertEqual(summary["requests"], 2)
        self.assertEqual(summary["errors"], 1)
        self.assertIsNotNone(summary["p95_ms"])


if __name__ == "__main__":
    unittest.main()
