"""Regression checks for the single-member team submission's first two detectors (stdlib only)."""
import unittest

from eval.prosecute import _hook_fabricated_citation, _hook_protocol_misuse, prosecute


PAGE = "Frame:d8f95a7b/w/045"


def event(seq, kind, **payload):
    return {"seq": seq, "type": kind, "p": payload}


class DetectorTests(unittest.TestCase):
    def test_span_and_revision_agnostic_citations_are_returned_pages(self):
        trace = [event(1, "tool_result", anchors=[PAGE]),
                 event(2, "answer", cited_anchors=[PAGE + "#s1", "Frame:d8f95a7b/045"])]
        self.assertEqual(_hook_fabricated_citation(trace, {}, {}), [])

    def test_other_revision_is_not_the_returned_page(self):
        trace = [event(1, "tool_result", anchors=[PAGE]),
                 event(2, "answer", cited_anchors=[PAGE.replace('/w/', '/c/')])]
        self.assertEqual(_hook_fabricated_citation(trace, {}, {})[0][0], ["evt:0002"])

    def test_structured_row_source_is_not_fabricated(self):
        trace = [event(1, "tool_result", anchors=["Concept:streamable-http"], rows=[{"anchor": PAGE}]),
                 event(2, "answer", cited_anchors=[PAGE])]
        self.assertEqual(_hook_fabricated_citation(trace, {}, {}), [])

    def test_search_does_not_require_a_lease(self):
        trace = [event(1, "command", server="slides", tool="search", lease_id=None)]
        self.assertEqual(_hook_protocol_misuse(trace, {}, {}), [])

    def test_missing_and_expired_get_frame_lease(self):
        for lease, code in ((None, None), ("old", "lease_expired")):
            with self.subTest(lease=lease):
                trace = [event(1, "command", server="slides", tool="get_frame", lease_id=lease),
                         event(2, "tool_result", error_code=code)]
                self.assertEqual(_hook_protocol_misuse(trace, {}, {})[0][0], ["evt:0001"])

    def test_partial_result_needs_matching_later_continuation(self):
        trace = [event(1, "command", server="slides", tool="query"),
                 event(2, "tool_result", partial=True, anchors=[PAGE])]
        answer = event(5, "answer", cited_anchors=[PAGE])
        self.assertEqual(_hook_protocol_misuse(trace + [answer], {}, {})[0][0], ["evt:0002", "evt:0005"])
        followup = event(3, "command", server="slides", tool="query", args={"continuation": "next"})
        self.assertEqual(_hook_protocol_misuse(trace + [followup, answer], {}, {}), [])
        followup["p"]["server"] = "research"
        self.assertTrue(_hook_protocol_misuse(trace + [followup, answer], {}, {}))

    def test_body_span_mask_defaults_and_wildcard(self):
        for mask in (["title"], ["body"], [], ["*"]):
            with self.subTest(mask=mask):
                trace = [event(1, "command", server="slides", tool="get_frame", lease_id="live", args={"anchor": PAGE}),
                         event(2, "tool_call", mask=mask),
                         event(3, "answer", cited_anchors=[PAGE + "#s1"])]
                self.assertEqual(bool(_hook_protocol_misuse(trace, {}, {})), mask == ["title"])

    def test_multiple_hits_preserve_one_claim_per_family(self):
        trace = [event(1, "command", server="slides", tool="get_frame", lease_id=None),
                 event(2, "command", server="slides", tool="get_frame", lease_id=None),
                 event(3, "answer", cited_anchors=[PAGE, PAGE.replace('045', '999')])]
        claims = prosecute(trace, {}, {})["claims"]
        self.assertEqual([c["cls"] for c in claims], ["protocol_misuse", "fabricated_citation"])


if __name__ == "__main__":
    unittest.main()
