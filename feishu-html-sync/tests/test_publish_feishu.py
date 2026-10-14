#!/usr/bin/env python3
"""Offline tests for box/publish_feishu.py."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "box"))
import publish_feishu as pf  # noqa: E402


SAMPLE = """<!doctype html>
<html><head><title>template title</title></head><body>
<div id="sheet">
  <div class="toolbar"><button>不要发布</button></div>
  <h1>测试财报</h1>
  <section><h2>核心结论</h2>
    <p>收入 &lt; 10，毛利率 ≥ 20% <b class="t f">事实</b></p>
    <ol><li>第一项结论 <b class="t f">事实</b></li></ol>
    <ul><li>第一项风险 <b class="t i">推断</b></li></ul>
    <div class="mod"><div class="sub">IPO 发行</div>
      <p>估值 ≤ 30；增长 &gt; 5 <b class="t i">推断</b></p>
      <table class="d"><thead><tr><th>项目</th><th>状态</th></tr></thead>
      <tbody><tr><td>库存</td><td><span class="nd">未披露</span></td></tr>
      <tr><td>口径</td><td>调整 <b class="t c">计算</b></td></tr></tbody></table>
    </div>
    <div class="mod"><div><strong>现金流</strong></div><p>经营现金流改善。</p></div>
    <figure><div class="ft">图 1 收入</div><canvas></canvas>
      <p class="src">来源：公司公告</p></figure>
  </section>
</div>
<template id="report-tpl"><div id="sheet"><p>{{stale}}</p></div></template>
</body></html>"""


def all_texts(report):
    texts = []
    for block in report["blocks"]:
        if block["block_type"] in pf.TEXT_KEYS:
            texts.append(pf._desired_text(block))
        if block["block_type"] == 31:
            texts.extend(cell["text"] for cell in block["_cells"])
    return texts


def fake_existing(doc_id, desired):
    root_children = []
    items = [{"block_id": doc_id, "block_type": 1, "children": root_children}]
    for number, block in enumerate(desired):
        block_id = f"b{number}"
        root_children.append(block_id)
        if block["block_type"] != 31:
            current = json.loads(json.dumps(pf.public_block(block)))
            current.update(block_id=block_id, parent_id=doc_id)
            items.append(current)
            continue
        table = json.loads(json.dumps(pf.public_block(block)))
        table.update(block_id=block_id, parent_id=doc_id, children=[])
        items.append(table)
        for cell_number, cell in enumerate(block["_cells"]):
            cell_id = f"{block_id}c{cell_number}"
            text_id = f"{cell_id}t"
            table["children"].append(cell_id)
            items.append({
                "block_id": cell_id,
                "block_type": 32,
                "parent_id": block_id,
                "children": [text_id],
            })
            text = json.loads(json.dumps(pf.text_block(cell["text"], bold=cell["bold"])))
            text.update(block_id=text_id, parent_id=cell_id)
            items.append(text)
    return {"data": {"items": items}}


class Conversion(unittest.TestCase):
    def test_inline_rendered_dom_conversion(self):
        report = pf.convert_source(SAMPLE)
        texts = all_texts(report)
        self.assertFalse(any("{{" in text for text in texts))
        self.assertTrue(any(block["block_type"] == 31 for block in report["blocks"]))
        self.assertTrue(any("核心结论" in text for text in texts))
        self.assertTrue(any("IPO" in text for text in texts))
        self.assertTrue(any("现金流" in text for text in texts))
        self.assertFalse(any("<" in text or ">" in text for text in texts))
        self.assertIn("未披露", texts)
        self.assertTrue(any("〔事实〕" in text for text in texts))
        self.assertTrue(any("〔计算〕" in text for text in texts))
        self.assertTrue(any("〔推断〕" in text for text in texts))
        self.assertIn("图表见 HTML 版", texts)
        self.assertIn("来源：公司公告", texts)
        ordered = next(block for block in report["blocks"] if block["block_type"] == 13)
        self.assertIn("ordered", ordered)
        bullet = next(block for block in report["blocks"] if block["block_type"] == 12)
        self.assertIn("bullet", bullet)

    @unittest.skipUnless(os.path.exists("/tmp/rv_dom.html"), "/tmp/rv_dom.html not present")
    def test_v71_rendered_snapshot(self):
        report = pf.convert_html("/tmp/rv_dom.html")
        texts = all_texts(report)
        self.assertFalse(any("{{" in text for text in texts))
        self.assertGreater(sum(block["block_type"] == 31 for block in report["blocks"]), 0)
        self.assertTrue(any("核心结论" in text for text in texts))
        self.assertTrue(any("IPO" in text for text in texts))
        self.assertFalse(any("<" in text or ">" in text for text in texts))
        self.assertTrue(any("未披露" in text for text in texts))
        self.assertTrue(any(
            marker in text for text in texts for marker in ("〔事实〕", "〔计算〕", "〔推断〕")
        ))

    @unittest.skipUnless(
        os.path.exists("/tmp/work/v72_dom.html"), "/tmp/work/v72_dom.html not present",
    )
    def test_v72_table_create_payloads_stay_within_api_limits(self):
        report = pf.convert_html("/tmp/work/v72_dom.html")
        operations = pf.content_operations("doc", report["blocks"])
        properties = [
            child["table"]["property"]
            for operation in operations
            for child in operation.get("json", {}).get("children", [])
            if child.get("block_type") == 31
        ]
        self.assertGreater(len(properties), 0)
        self.assertTrue(all(
            prop["row_size"] <= 9 and prop["column_size"] <= 9
            for prop in properties
        ))

    def test_children_batches_never_exceed_fifty(self):
        blocks = [pf.text_block(f"段落 {index}") for index in range(121)]
        operations = pf.content_operations("doc", blocks)
        batches = [
            operation["json"]["children"]
            for operation in operations
            if operation["method"] == "POST"
        ]
        self.assertEqual([len(batch) for batch in batches], [50, 50, 21])
        self.assertTrue(all(len(batch) <= 50 for batch in batches))


class ExistingDocumentUpdates(unittest.TestCase):
    def test_changed_text_generates_only_one_patch(self):
        report = pf.convert_source(SAMPLE)
        existing = fake_existing("doc1", report["blocks"])
        # Make exactly one existing paragraph stale.
        stale = next(
            item for item in existing["data"]["items"]
            if item.get("block_type") == 2
            and "收入" in pf._existing_text(item)
        )
        stale["text"]["elements"][0]["text_run"]["content"] = "旧收入结论"

        plan = pf.plan_updates("doc1", report["blocks"], existing)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(len(plan["operations"]), 1)
        self.assertTrue(all(op["method"] == "PATCH" for op in plan["operations"]))
        self.assertEqual(
            plan["operations"][0]["json"],
            {
                "update_text_elements": {
                    "elements": [{
                        "text_run": {
                            "content": "收入 低于 10，毛利率 不低于 20% 〔事实〕"
                        }
                    }]
                }
            },
        )

    def test_changed_list_text_uses_native_list_block_patch(self):
        report = pf.convert_source(SAMPLE)
        existing = fake_existing("doc1", report["blocks"])
        stale = next(
            item for item in existing["data"]["items"]
            if item.get("block_type") == 13
        )
        stale["ordered"]["elements"][0]["text_run"]["content"] = "旧结论"
        plan = pf.plan_updates("doc1", report["blocks"], existing)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(len(plan["operations"]), 1)
        self.assertEqual(plan["operations"][0]["method"], "PATCH")
        self.assertNotIn("batch_update", plan["operations"][0]["url"])

    def test_changed_table_cell_uses_batch_update(self):
        report = pf.convert_source(SAMPLE)
        existing = fake_existing("doc1", report["blocks"])
        stale = next(
            item for item in existing["data"]["items"]
            if item.get("block_type") == 2
            and pf._existing_text(item) == "库存"
        )
        stale["text"]["elements"][0]["text_run"]["content"] = "旧库存"
        plan = pf.plan_updates("doc1", report["blocks"], existing)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(len(plan["operations"]), 1)
        operation = plan["operations"][0]
        self.assertEqual(operation["method"], "PATCH")
        self.assertIn("/blocks/batch_update?", operation["url"])
        self.assertEqual(len(operation["json"]["requests"]), 1)
        self.assertEqual(
            operation["json"]["requests"][0]["update_text_elements"]["elements"][0]
            ["text_run"]["content"],
            "库存",
        )

    def test_structure_mismatch_refuses_without_replace_all(self):
        report = pf.convert_source(SAMPLE)
        existing = fake_existing("doc1", report["blocks"][:-1])
        plan = pf.plan_updates("doc1", report["blocks"], existing)
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["operations"], [])
        self.assertIn("count differs", plan["diff"][0])

    def test_dry_cli_writes_payload_without_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            html = os.path.join(directory, "rendered.html")
            output = os.path.join(directory, "payload.json")
            with open(html, "w", encoding="utf-8") as handle:
                handle.write(SAMPLE)
            result = pf.main(["docx", "--html", html, "--dry", "--out", output])
            self.assertEqual(result, 0)
            with open(output, encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["mode"], "docx-create")
            self.assertTrue(all(
                len(op["json"]["children"]) <= 50
                for op in payload["operations"]
                if "children" in op.get("json", {})
            ))


class TablePlanning(unittest.TestCase):
    @staticmethod
    def fake_table(rows=38, columns=9):
        return {
            "block_type": 31,
            "table": {
                "property": {
                    "row_size": rows,
                    "column_size": columns,
                    "header_row": True,
                }
            },
            "_cells": [
                {"text": f"r{row}c{column}", "bold": row == 0}
                for row in range(rows)
                for column in range(columns)
            ],
        }

    def test_38_row_table_create_insert_and_batch_limits(self):
        operations = pf.content_operations("doc", [self.fake_table()])
        creates = [
            operation for operation in operations
            if operation["method"] == "POST"
            and operation.get("json", {}).get("children", [{}])[0].get("block_type") == 31
        ]
        self.assertEqual(len(creates), 1)
        prop = creates[0]["json"]["children"][0]["table"]["property"]
        self.assertEqual((prop["row_size"], prop["column_size"]), (9, 9))
        self.assertTrue(prop["header_row"])
        inserts = [
            operation for operation in operations
            if "insert_table_row" in operation.get("json", {})
        ]
        self.assertEqual(len(inserts), 29)
        gets = [
            operation for operation in operations
            if operation["method"] == "GET" and "/blocks/" in operation["url"]
        ]
        self.assertEqual(len(gets), 1)
        batches = [
            operation["json"]["requests"] for operation in operations
            if "/blocks/batch_update?" in operation["url"]
        ]
        self.assertEqual([len(batch) for batch in batches], [200, 142])
        self.assertTrue(all(len(batch) <= 200 for batch in batches))

    def test_wide_html_table_splits_columns_and_repeats_first(self):
        headings = "".join(f"<th>h{column}</th>" for column in range(11))
        values = "".join(f"<td>v{column}</td>" for column in range(11))
        source = (
            '<div id="sheet"><h1>宽表</h1><table class="d"><thead><tr>'
            + headings + "</tr></thead><tbody><tr>" + values
            + "</tr></tbody></table></div>"
        )
        report = pf.convert_source(source)
        tables = [block for block in report["blocks"] if block["block_type"] == 31]
        self.assertEqual([pf._table_shape(table) for table in tables], [(2, 9), (2, 3)])
        self.assertTrue(all(pf._table_shape(table)[1] <= 9 for table in tables))
        self.assertEqual(tables[0]["_cells"][0]["text"], "h0")
        self.assertEqual(tables[1]["_cells"][0]["text"], "h0")
        operations = pf.content_operations("doc", report["blocks"])
        create_props = [
            child["table"]["property"]
            for operation in operations
            for child in operation.get("json", {}).get("children", [])
            if child.get("block_type") == 31
        ]
        self.assertTrue(all(
            prop["row_size"] <= 9 and prop["column_size"] <= 9
            for prop in create_props
        ))

    def test_live_append_path_patches_existing_cell_text_blocks(self):
        table = self.fake_table()

        class FakeClient:
            def __init__(self):
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                body = kwargs.get("json_body") or {}
                if method == "POST" and "/children?" in url:
                    return {"data": {"children": [{"block_id": "table1"}]}}
                if method == "GET" and url.endswith("/blocks/table1"):
                    return {
                        "data": {
                            "block": {
                                "block_id": "table1",
                                "block_type": 31,
                                "table": {
                                    "property": {
                                        "row_size": 38,
                                        "column_size": 9,
                                    },
                                    "cells": [f"cell{index}" for index in range(342)],
                                },
                            }
                        }
                    }
                if method == "GET" and url.endswith("/blocks"):
                    return {
                        "data": {
                            "items": [
                                {
                                    "block_id": f"text{index}",
                                    "block_type": 2,
                                    "parent_id": f"cell{index}",
                                    "text": {"elements": [{"text_run": {"content": ""}}]},
                                }
                                for index in range(342)
                            ],
                            "has_more": False,
                        }
                    }
                if method == "PATCH" and "insert_table_row" in body:
                    return {"data": {}}
                if method == "PATCH" and "/blocks/batch_update?" in url:
                    return {"data": {}}
                raise AssertionError(f"unexpected request: {method} {url} {kwargs}")

        client = FakeClient()
        pf.append_content(client, "doc", [table])
        insert_calls = [
            call for call in client.calls
            if "insert_table_row" in (call[2].get("json_body") or {})
        ]
        self.assertEqual(len(insert_calls), 29)
        batch_calls = [
            call for call in client.calls if "/blocks/batch_update?" in call[1]
        ]
        self.assertEqual(
            [len(call[2]["json_body"]["requests"]) for call in batch_calls],
            [200, 142],
        )
        self.assertFalse(any(
            method == "POST" and "/blocks/cell" in url
            for method, url, _ in client.calls
        ))


class DriveDryRun(unittest.TestCase):
    def test_drive_plan_is_offline_and_overwrites_given_token(self):
        with tempfile.TemporaryDirectory() as directory:
            html = os.path.join(directory, "report.html")
            with open(html, "wb") as handle:
                handle.write(b"<html>report</html>")
            plan = pf.drive_dry_plan("existing-token", html)
        self.assertEqual([op["method"] for op in plan["operations"]], [
            "POST", "POST", "POST", "GET",
        ])
        upload = plan["operations"][2]
        self.assertEqual(upload["multipart"]["fields"], {
            "file_name": "${metadata.title}",
            "parent_type": "explorer",
            "size": "19",
            "file_token": "existing-token",
        })
        self.assertEqual(
            upload["assert"]["response.data.file_token"], "existing-token",
        )


if __name__ == "__main__":
    unittest.main()
