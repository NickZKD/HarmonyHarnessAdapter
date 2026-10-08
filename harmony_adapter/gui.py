from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from urllib.parse import parse_qs, urlparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from harmony_adapter.adapter import HarmonyAdapter
from harmony_adapter.benchmark import CASES, default_harnesses, bitfun_harness, codex_harness, run_benchmark
from harmony_adapter.benchmark_factory import generate_factory, materialize_default_seed_repos
from harmony_adapter.config import HarmonyConfig
from harmony_adapter.history import append_evaluation_history, read_evaluation_history
from harmony_adapter.models import TaskSpec
from harmony_adapter.prompts import DEFAULT_PROMPT_TEMPLATE
from harmony_adapter.utils import write_json

GUI_CONFIG_PATH = Path("artifacts") / "gui_config.json"


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HarmonyAdapter</title>
  <style>
    :root {
      --ink: #17202d;
      --muted: #657184;
      --line: #d9e0ea;
      --panel: #ffffff;
      --page: #f5f7fa;
      --accent: #156b68;
      --accent-strong: #0d4f4c;
      --warn: #9b5419;
      --bad: #a23434;
      --ok: #217348;
      --soft: #eef3f6;
      --code: #111827;
      --code-bg: #f8f4ee;
      --focus: #d9eeec;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--page);
      color: var(--ink);
      font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      min-height: 62px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 22px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }
    h1, h2, h3 { margin: 0; letter-spacing: 0; }
    h1 { font-size: 18px; }
    h2 { font-size: 15px; }
    h3 { font-size: 13px; color: var(--muted); }
    .brand { display: flex; align-items: center; gap: 10px; }
    .mark {
      width: 22px;
      height: 22px;
      border-radius: 6px;
      background: conic-gradient(from 45deg, #156b68, #5e78bd, #c46b43, #156b68);
      border: 1px solid rgba(0, 0, 0, .12);
    }
    .top-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .status-line { color: var(--muted); font-size: 13px; }
    main {
      display: grid;
      gap: 14px;
      padding: 16px;
      max-width: 1440px;
      margin: 0 auto;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }
    .panel-body { padding: 14px; }
    .grid {
      display: grid;
      grid-template-columns: minmax(360px, 1fr) minmax(420px, 1.3fr);
      gap: 14px;
      align-items: start;
    }
    .stack { display: grid; gap: 14px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    button {
      min-height: 34px;
      border: 1px solid #bac5d2;
      border-radius: 6px;
      padding: 7px 11px;
      background: #fff;
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      font-weight: 680;
      white-space: nowrap;
    }
    button.primary { border-color: var(--accent-strong); background: var(--accent); color: white; }
    button:disabled { opacity: .58; cursor: wait; }
    .segmented { display: inline-flex; border: 1px solid #bac5d2; border-radius: 6px; overflow: hidden; }
    .segmented button {
      border: 0;
      border-radius: 0;
      min-height: 32px;
      padding: 6px 10px;
    }
    .segmented button.active { background: var(--accent); color: #fff; }
    .summary {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }
    .metric, .control-pill {
      border: 1px solid #e1e7ef;
      border-radius: 6px;
      padding: 10px;
      background: #fff;
      min-width: 0;
    }
    .metric span, .control-pill span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 720;
    }
    .metric strong, .control-pill strong {
      display: block;
      margin-top: 3px;
      overflow-wrap: anywhere;
    }
    .control-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }
    .config-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      align-items: end;
    }
    .config-grid label.checkbox-row {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 38px;
    }
    .config-grid input[type="checkbox"] { width: auto; }
    .conditions-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .condition-card {
      border: 1px solid #dfe5ec;
      border-radius: 8px;
      background: #fff;
      padding: 11px;
      display: grid;
      gap: 8px;
      min-width: 0;
    }
    .condition-card button {
      justify-self: start;
      min-height: 30px;
      padding: 5px 9px;
    }
    .condition-title { font-weight: 760; }
    .condition-summary { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
    .factory-panel { border-top: 1px solid var(--line); margin-top: 12px; padding-top: 12px; }
    .section-head.compact { margin-bottom: 10px; }
    .factory-list { display: grid; gap: 8px; margin-top: 10px; }
    .repo-list { display: grid; gap: 8px; }
    .repo-item {
      display: grid;
      grid-template-columns: minmax(180px, 1fr) auto;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 9px 10px;
    }
    .factory-item {
      display: grid;
      grid-template-columns: minmax(160px, 1.2fr) 110px minmax(120px, 1fr) auto auto;
      align-items: center;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 10px;
    }
    .factory-item strong { font-size: 13px; overflow-wrap: anywhere; }
    .factory-item span { color: var(--muted); font-size: 12px; }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 22px;
      background: rgba(23, 32, 45, .42);
      z-index: 20;
    }
    .modal-backdrop.open { display: flex; }
    .modal {
      width: min(920px, 100%);
      max-height: min(760px, calc(100vh - 44px));
      background: #fff;
      border: 1px solid #cfd8e4;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 22px 70px rgba(23, 32, 45, .26);
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .modal-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }
    .modal-body { overflow: auto; }
    .modal-body pre { min-height: 0; max-height: none; }
    .harness-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .harness-card {
      border: 1px solid #dfe5ec;
      border-radius: 8px;
      padding: 11px;
      background: #fff;
      display: grid;
      gap: 8px;
      min-width: 0;
    }
    .harness-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
    .harness-name { font-weight: 760; overflow-wrap: anywhere; }
    .harness-desc { color: var(--muted); font-size: 12px; min-height: 34px; }
    .harness-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      padding-top: 2px;
    }
    .kv {
      display: grid;
      grid-template-columns: 70px minmax(0, 1fr);
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .kv strong { color: var(--ink); font-weight: 680; overflow-wrap: anywhere; }
    .badge {
      width: max-content;
      max-width: 100%;
      padding: 2px 7px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 760;
      align-self: start;
    }
    .ok { color: var(--ok); background: #eaf5ef; }
    .error { color: var(--bad); background: #f8eaea; }
    .missing { color: var(--warn); background: #fff0df; }
    .results-table { width: 100%; border-collapse: collapse; }
    .results-table th, .results-table td {
      border-bottom: 1px solid #e6ebf1;
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }
    .results-table th { color: var(--muted); font-size: 12px; font-weight: 760; background: #fbfcfd; }
    .results-table tr.case-row td { background: #fbfcfd; font-size: 12px; }
    .history-list { display: grid; gap: 8px; }
    .history-item {
      display: grid;
      grid-template-columns: minmax(160px, 1fr) 95px 90px 120px auto;
      gap: 8px;
      align-items: center;
      padding: 9px 10px;
      border: 1px solid #e1e6ee;
      border-radius: 6px;
      background: #fff;
      font-size: 12px;
    }
    .history-title { font-weight: 760; overflow-wrap: anywhere; }
    .history-meta { color: var(--muted); overflow-wrap: anywhere; }
    .detail-link {
      min-height: 0;
      border: 0;
      padding: 0;
      background: transparent;
      color: var(--accent-strong);
      text-decoration: underline;
      text-underline-offset: 2px;
      font-weight: 760;
      white-space: normal;
    }
    .empty {
      min-height: 182px;
      display: grid;
      place-items: center;
      color: var(--muted);
      padding: 18px;
      text-align: center;
    }
    .tabs {
      display: flex;
      gap: 4px;
      padding: 8px 8px 0;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }
    .tab { border-bottom-left-radius: 0; border-bottom-right-radius: 0; border-bottom-color: transparent; }
    .tab.active {
      background: #fff;
      color: var(--accent-strong);
      border-color: var(--line);
      border-bottom-color: #fff;
    }
    pre {
      margin: 0;
      padding: 14px;
      min-height: 260px;
      max-height: 420px;
      overflow: auto;
      background: var(--code-bg);
      color: var(--code);
      font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    details { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
    summary { cursor: pointer; padding: 12px 14px; font-weight: 760; background: #fbfcfd; }
    label { display: grid; gap: 6px; color: #334155; font-size: 12px; font-weight: 680; }
    input, textarea, select {
      width: 100%;
      border: 1px solid #c7d0dc;
      border-radius: 6px;
      padding: 9px 10px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      letter-spacing: 0;
    }
    textarea {
      min-height: 76px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
    }
    input:focus, textarea:focus, select:focus { outline: 3px solid var(--focus); border-color: var(--accent); }
    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .tool-list { display: grid; gap: 8px; }
    .tool {
      display: grid;
      grid-template-columns: 78px minmax(0, 1fr);
      gap: 8px;
      padding: 9px 10px;
      border: 1px solid #e1e6ee;
      border-radius: 6px;
      background: #fff;
    }
    .tool-path, .mono-line {
      overflow-wrap: anywhere;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
    }
    .note { color: var(--muted); font-size: 12px; margin-top: 8px; }
    @media (max-width: 1040px) {
      .grid { grid-template-columns: 1fr; }
      .summary, .control-grid, .conditions-grid, .config-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 620px) {
      header { align-items: flex-start; flex-direction: column; padding: 12px 14px; }
      .top-actions { justify-content: flex-start; }
      .summary, .control-grid, .conditions-grid, .harness-grid, .form-grid, .history-item, .factory-item, .config-grid, .repo-item { grid-template-columns: 1fr; }
      .actions button { flex: 1 1 150px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand"><span class="mark" aria-hidden="true"></span><h1>HarmonyAdapter</h1></div>
    <div class="top-actions">
      <div class="segmented" aria-label="Language">
        <button id="langZh" class="active">中文</button>
        <button id="langEn">EN</button>
      </div>
      <div class="status-line" id="statusLine">Ready</div>
    </div>
  </header>
  <main>
    <section>
      <div class="section-head">
        <h2 data-i18n="controlConditions">控制条件</h2>
        <div class="actions">
          <button id="conditionsJsonBtn" title="View all conditions" data-i18n="viewAllConditions">查看全部</button>
          <button id="doctorBtn" title="Run doctor" data-i18n="checkTools">检查工具</button>
          <button id="refreshHarnessBtn" title="Refresh harness status" data-i18n="refresh">刷新</button>
          <button id="benchmarkBtn" class="primary" title="Run benchmark demo" data-i18n="runBenchmark">运行评测</button>
        </div>
      </div>
      <div class="panel-body stack">
        <div class="summary">
          <div class="metric"><span data-i18n="toolchain">工具链</span><strong id="toolSummary">Not checked</strong></div>
          <div class="metric"><span data-i18n="harnessCount">Harness</span><strong id="mHarnessCount">0</strong></div>
          <div class="metric"><span data-i18n="bestScore">最高分</span><strong id="mBestScore">n/a</strong></div>
          <div class="metric"><span data-i18n="tokenUsage">Token</span><strong id="mTokens">n/a</strong></div>
          <div class="metric"><span data-i18n="artifactRoot">产物目录</span><strong id="mArtifacts">None</strong></div>
        </div>
        <div class="control-grid">
          <div class="control-pill"><span data-i18n="prompt">Prompt</span><strong id="dPrompt">prompt.txt</strong></div>
          <div class="control-pill"><span data-i18n="budget">预算</span><strong id="dBudget">120s / 200000</strong></div>
          <div class="control-pill"><span data-i18n="buildValidation">构建验证</span><strong id="dBuild">assembleHap</strong></div>
          <div class="control-pill"><span data-i18n="cases">测试用例</span><strong id="dCases">0</strong></div>
        </div>
        <div class="config-grid">
          <label><span data-i18n="timeoutSec">Timeout Sec</span><input id="cfgTimeout" type="number" min="1"></label>
          <label><span data-i18n="maxTokens">Max Tokens</span><input id="cfgMaxTokens" type="number" min="1"></label>
          <label><span data-i18n="buildTarget">Build Target</span><input id="cfgBuildTarget"></label>
          <label><span data-i18n="modelChoice">模型变量</span><select id="modelSelect"><option value="" data-i18n="defaultModel">Harness 默认</option></select></label>
          <label class="checkbox-row"><input id="cfgRunBuild" type="checkbox"><span data-i18n="runBuild">运行构建验证</span></label>
          <label class="checkbox-row"><input id="cfgRequireModelLock" type="checkbox"><span data-i18n="requireModelLock">要求模型锁定</span></label>
          <label><span data-i18n="requiredModel">Required Model</span><input id="cfgRequiredModel" placeholder="optional"></label>
          <div class="actions"><button id="saveConfigBtn" class="primary" data-i18n="saveConfig">保存配置</button></div>
        </div>
        <div class="conditions-grid" id="conditionsGrid"></div>
        <div class="note" data-i18n="conditionsNote">上方为当前数据，下方可调整配置并保存；评测和用例生成会读取保存后的配置。</div>
        <div class="factory-panel">
          <div class="section-head compact">
            <h2 data-i18n="factoryTitle">Benchmark Factory</h2>
            <div class="actions">
              <button id="factoryDetailBtn" title="View factory details" data-i18n="viewDetail">查看详情</button>
              <button id="addGeneratedBtn" data-i18n="addGenerated">加入测试集</button>
              <button id="factoryBtn" title="Generate task packages" data-i18n="generateFactory">生成任务包</button>
            </div>
          </div>
          <div class="form-grid">
            <label><span data-i18n="repoPath">Repository Path</span><input id="factoryRepoInput" placeholder="/path/to/harmony/repo"></label>
            <div class="actions"><button id="addRepoBtn" data-i18n="addRepo">添加仓库</button><button id="runFactorySetBtn" data-i18n="runFactorySet">运行测试集</button></div>
          </div>
          <div class="repo-list" id="factoryRepoList"></div>
          <div class="summary">
            <div class="metric"><span data-i18n="factoryTasks">Task Packages</span><strong id="mFactoryTasks">0</strong></div>
            <div class="metric"><span data-i18n="factoryRepos">Seed Repos</span><strong id="mFactoryRepos">0</strong></div>
            <div class="metric"><span data-i18n="execSet">Executable Set</span><strong id="mExecSet">0</strong></div>
            <div class="metric"><span data-i18n="factoryOutput">Output</span><strong id="mFactoryOutput">None</strong></div>
          </div>
          <div class="factory-list" id="factoryList"></div>
        </div>
      </div>
    </section>

    <div class="grid">
      <section>
        <div class="section-head">
          <h2 data-i18n="harnesses">Harness 状态</h2>
        </div>
        <div class="panel-body">
          <div class="harness-grid" id="harnessGrid"></div>
          <div class="note" data-i18n="harnessNote">unsupported/auth_required/config_error 是环境或配置问题，不计入能力分。</div>
        </div>
      </section>

      <section>
        <div class="section-head">
          <h2 data-i18n="results">评测结果</h2>
        </div>
        <div id="resultsView" class="empty" data-i18n="emptyResults">点击“运行评测”后查看结果。</div>
      </section>
    </div>

    <section>
      <div class="section-head">
        <h2 data-i18n="history">历史记录</h2>
        <button id="refreshHistoryBtn" title="Refresh history" data-i18n="refresh">刷新</button>
      </div>
      <div class="panel-body">
        <div class="history-list" id="historyList"></div>
      </div>
    </section>

    <section>
      <div class="tabs">
        <button class="tab active" data-tab="benchmark" data-i18n="tabBenchmark">Benchmark</button>
        <button class="tab" data-tab="contract" data-i18n="tabContract">Contract</button>
        <button class="tab" data-tab="metadata" data-i18n="tabMetadata">Metadata</button>
        <button class="tab" data-tab="patch" data-i18n="tabPatch">Patch</button>
      </div>
      <div id="output" class="empty" data-i18n="emptyOutput">这里会显示本次评测的详细 JSON、控制变量和产物位置。</div>
    </section>

    <section>
      <div class="section-head">
        <h2 data-i18n="toolDetails">工具链详情</h2>
      </div>
      <div class="panel-body">
        <div class="tool-list" id="toolList"></div>
      </div>
    </section>

    <details>
      <summary data-i18n="advanced">高级：运行单个自定义任务</summary>
      <div class="panel-body stack">
        <div class="form-grid">
          <label><span data-i18n="instanceId">Instance ID</span><input id="instanceId" value="demo-harmony-001"></label>
          <label><span data-i18n="runId">Run ID</span><input id="runId" value="gui-run"></label>
        </div>
        <label><span data-i18n="repoPath">Repository Path</span><input id="repo" placeholder="/path/to/harmony/project"></label>
        <label><span data-i18n="instruction">Instruction</span><textarea id="instruction">把 App.ets 中的 ability 状态改成已实现。</textarea></label>
        <label><span data-i18n="harnessCommand">Harness Command</span><textarea id="harnessCommand" placeholder="python3 harness.py --prompt {prompt} --workspace {workspace}"></textarea></label>
        <div class="form-grid">
          <label><span data-i18n="artifactsRootInput">Artifacts Root</span><input id="artifactsRoot" value="/private/tmp/harmony_adapter_gui_artifacts"></label>
          <label><span data-i18n="model">Model</span><input id="model" value="gui-model"></label>
        </div>
        <div class="form-grid">
          <label><span data-i18n="timeoutSec">Timeout Sec</span><input id="timeoutSec" type="number" min="1" value="3600"></label>
          <label><span data-i18n="maxTokens">Max Tokens</span><input id="maxTokens" type="number" min="1" placeholder="optional"></label>
        </div>
        <label><span data-i18n="criteria">Evaluation Criteria</span><textarea id="evaluationCriteria">Harness-owned tests and reports decide pass/fail. The adapter records runner-side git diff as the accepted patch.</textarea></label>
        <div class="actions">
          <button id="runBtn" class="primary" title="Run custom task" data-i18n="runTask">运行任务</button>
          <button id="loadDemoBtn" title="Load demo values" data-i18n="loadDemo">载入示例</button>
          <button id="demoBtn" title="Run demo" data-i18n="runDemo">跑示例</button>
        </div>
      </div>
    </details>
  </main>
  <div class="modal-backdrop" id="detailModal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
    <div class="modal">
      <div class="modal-head">
        <h2 id="modalTitle">Detail</h2>
        <button id="closeModalBtn" title="Close" data-i18n="close">关闭</button>
      </div>
      <div class="modal-body" id="modalBody"></div>
    </div>
  </div>
  <script>
    const state = { tab: "benchmark", result: null, conditions: null, config: null, factory: null, detail: null, models: [], lang: localStorage.getItem("harmonyAdapterLang") || "zh" };
    const $ = (id) => document.getElementById(id);
    const copy = {
      zh: {
        overview: "评测总览", controlConditions: "控制条件", checkTools: "检查工具", refresh: "刷新", runBenchmark: "运行评测",
        toolchain: "工具链", harnessCount: "Harness", bestScore: "最高分", artifactRoot: "产物目录",
        tokenUsage: "Token", history: "历史记录", emptyHistory: "还没有历史评测记录。", modelChoice: "模型变量", defaultModel: "Harness 默认",
        prompt: "Prompt", environment: "环境", budget: "预算", patch: "Patch", evaluation: "评价",
        harnesses: "Harness 状态", harnessNote: "unsupported/auth_required/config_error 是环境或配置问题，不计入能力分。",
        conditions: "评测条件", viewAllConditions: "查看全部", conditionsNote: "上方为当前数据，下方可调整配置并保存；评测和用例生成会读取保存后的配置。", close: "关闭",
        results: "评测结果", emptyResults: "点击“运行评测”后查看结果。",
        tabBenchmark: "Benchmark", tabContract: "Contract", tabMetadata: "Metadata", tabPatch: "Patch",
        emptyOutput: "这里会显示本次评测的详细 JSON、控制变量和产物位置。",
        toolDetails: "工具链详情", advanced: "高级：运行单个自定义任务",
        instanceId: "Instance ID", runId: "Run ID", repoPath: "Repository Path", instruction: "Instruction",
        harnessCommand: "Harness Command", artifactsRootInput: "Artifacts Root", model: "Model",
        timeoutSec: "Timeout Sec", maxTokens: "Max Tokens", criteria: "Evaluation Criteria",
        runTask: "运行任务", loadDemo: "载入示例", runDemo: "跑示例",
        ready: "就绪", running: "运行中", checking: "检查中", checked: "工具链已检查",
        benchmarkDone: "评测完成", taskDone: "任务完成", demoLoaded: "示例已载入",
        notChecked: "未检查", needsAttention: "需要处理", score: "分数", passed: "通过", status: "状态",
        issue: "问题", modelLabel: "模型", command: "命令", noResults: "尚未运行", none: "无",
        harness: "Harness", passRate: "通过率", artifacts: "产物", details: "详情", createdAt: "时间",
        viewDetail: "查看详情", promptTemplate: "Prompt 模板", envVars: "环境变量", patchRule: "Patch 规则",
        evalSet: "评估集", modelLock: "模型锁", buildValidation: "构建验证", cases: "测试用例",
        fixedPrompt: "每个任务由 adapter 写入 prompt.txt", fixedEnv: "统一导出 DevEco/Node/PATH", fixedBudget: "统一 timeout/token/turn 预算",
        fixedPatch: "统一从 workspace 抽取 git diff --binary", fixedEval: "oracle + patch scope + 可选 hvigor 构建", fixedModel: "通过 wrapper probe 检查模型是否锁定",
        runModel: "调用模型", debugHarness: "调试", confirmRunModel: "这会真实调用该 Harness 背后的模型并产生用量，确定继续？", harnessDone: "单个 Harness 评测完成",
        confirmDebugHarness: "这会对 BitFun 发起一次极小模型调用用于诊断，可能产生少量用量，确定继续？", debugDone: "调试完成",
        factoryTitle: "Benchmark Factory", generateFactory: "生成任务包", factoryTasks: "Task Packages", factoryRepos: "Seed Repos",
        factoryOutput: "Output", emptyFactory: "还没有生成 Task Package。", factoryDone: "Benchmark Factory 已生成",
        buildTarget: "Build Target", runBuild: "运行构建验证", requireModelLock: "要求模型锁定", requiredModel: "Required Model",
        saveConfig: "保存配置", configSaved: "配置已保存", addRepo: "添加仓库", remove: "移除", addGenerated: "加入测试集",
        addedGenerated: "已加入测试集", execSet: "Executable Set", runFactorySet: "运行测试集", factorySetDone: "测试集运行完成",
        confirmRunFactorySet: "这会对测试集里的 Task Package 调用 Harness/模型，确定继续？"
      },
      en: {
        overview: "Evaluation Overview", controlConditions: "Control Conditions", checkTools: "Check Tools", refresh: "Refresh", runBenchmark: "Run Benchmark",
        toolchain: "Toolchain", harnessCount: "Harnesses", bestScore: "Best Score", artifactRoot: "Artifacts",
        tokenUsage: "Tokens", history: "History", emptyHistory: "No evaluation history yet.", modelChoice: "Model Variable", defaultModel: "Harness default",
        prompt: "Prompt", environment: "Environment", budget: "Budget", patch: "Patch", evaluation: "Evaluation",
        harnesses: "Harness Status", harnessNote: "unsupported/auth_required/config_error are setup issues and are not capability scores.",
        conditions: "Evaluation Conditions", viewAllConditions: "View All", conditionsNote: "The top row presents current data; edit and save settings below. Runs and task generation use the saved config.", close: "Close",
        results: "Results", emptyResults: "Run the benchmark to see results.",
        tabBenchmark: "Benchmark", tabContract: "Contract", tabMetadata: "Metadata", tabPatch: "Patch",
        emptyOutput: "Detailed JSON, control variables, and artifact paths will appear here.",
        toolDetails: "Toolchain Details", advanced: "Advanced: Run One Custom Task",
        instanceId: "Instance ID", runId: "Run ID", repoPath: "Repository Path", instruction: "Instruction",
        harnessCommand: "Harness Command", artifactsRootInput: "Artifacts Root", model: "Model",
        timeoutSec: "Timeout Sec", maxTokens: "Max Tokens", criteria: "Evaluation Criteria",
        runTask: "Run Task", loadDemo: "Load Demo", runDemo: "Run Demo",
        ready: "Ready", running: "Running", checking: "Checking", checked: "Toolchain checked",
        benchmarkDone: "Benchmark completed", taskDone: "Task completed", demoLoaded: "Demo loaded",
        notChecked: "Not checked", needsAttention: "Needs attention", score: "Score", passed: "Passed", status: "Status",
        issue: "Issue", modelLabel: "Model", command: "Command", noResults: "Not run", none: "None",
        harness: "Harness", passRate: "Pass Rate", artifacts: "Artifacts", details: "Details", createdAt: "Time",
        viewDetail: "View Detail", promptTemplate: "Prompt Template", envVars: "Environment", patchRule: "Patch Rule",
        evalSet: "Evaluation Set", modelLock: "Model Lock", buildValidation: "Build Validation", cases: "Cases",
        fixedPrompt: "Adapter writes prompt.txt for every task", fixedEnv: "Exports fixed DevEco/Node/PATH values", fixedBudget: "Controls timeout/token/turn budgets",
        fixedPatch: "Collects git diff --binary from the workspace", fixedEval: "Oracle + patch scope + optional hvigor build", fixedModel: "Wrappers probe whether the model is locked",
        runModel: "Call Model", debugHarness: "Debug", confirmRunModel: "This will call the model behind this harness and may incur usage. Continue?", harnessDone: "Single harness completed",
        confirmDebugHarness: "This will make a tiny BitFun model call for diagnostics and may incur small usage. Continue?", debugDone: "Debug completed",
        factoryTitle: "Benchmark Factory", generateFactory: "Generate Tasks", factoryTasks: "Task Packages", factoryRepos: "Seed Repos",
        factoryOutput: "Output", emptyFactory: "No task packages generated yet.", factoryDone: "Benchmark Factory generated",
        buildTarget: "Build Target", runBuild: "Run build validation", requireModelLock: "Require model lock", requiredModel: "Required Model",
        saveConfig: "Save Config", configSaved: "Config saved", addRepo: "Add Repo", remove: "Remove", addGenerated: "Add to Test Set",
        addedGenerated: "Added to test set", execSet: "Executable Set", runFactorySet: "Run Test Set", factorySetDone: "Test set completed",
        confirmRunFactorySet: "This will call harnesses/models for task packages in the test set. Continue?"
      }
    };
    const t = (key) => copy[state.lang][key] || key;

    function applyLanguage() {
      document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
      for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
      $("langZh").classList.toggle("active", state.lang === "zh");
      $("langEn").classList.toggle("active", state.lang === "en");
      if (!state.result) {
        $("toolSummary").textContent = t("notChecked");
        $("mBestScore").textContent = "n/a";
        $("mTokens").textContent = "n/a";
        $("mArtifacts").textContent = t("none");
      }
      renderHarnesses(state.harnesses || [], state.result?.summary?.harnesses || null);
      renderModels(state.models || []);
      renderConditions();
      renderFactory();
      renderConfig();
      renderResultsTable();
      renderTab();
    }

    function setBusy(isBusy, key) {
      $("statusLine").textContent = key ? t(key) : (isBusy ? t("running") : t("ready"));
      for (const button of document.querySelectorAll("button")) button.disabled = isBusy;
    }

    async function requestJson(path, options = {}) {
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || response.statusText);
      return data;
    }

    function badgeClass(status) {
      if (status === "ready" || status === "scored") return "ok";
      if (status === "error" || status === "config_error" || status === "model_unlocked" || status === "auth_required") return "error";
      return "missing";
    }

    function displayValue(value) {
      if (value === null || value === undefined || value === "") return "n/a";
      return String(value);
    }

    function displayTokens(usage) {
      const total = usage && typeof usage.total === "number" ? usage.total : null;
      return total === null ? "n/a" : total.toLocaleString();
    }

    function selectedModel() {
      return $("modelSelect")?.value || "";
    }

    function renderConfig() {
      const config = state.config;
      if (!config) return;
      $("cfgTimeout").value = config.timeout_sec ?? 120;
      $("cfgMaxTokens").value = config.max_tokens ?? 200000;
      $("cfgBuildTarget").value = config.build_target || "assembleHap";
      $("cfgRunBuild").checked = !!config.run_build;
      $("cfgRequireModelLock").checked = !!config.require_model_lock;
      $("cfgRequiredModel").value = config.required_model || "";
      if ($("modelSelect")) $("modelSelect").value = config.selected_model || "";
      $("dBudget").textContent = `${config.timeout_sec || 120}s / ${config.max_tokens || "n/a"}`;
      $("dBuild").textContent = config.run_build ? (config.build_target || "assembleHap") : "disabled";
      $("dCases").textContent = `${state.conditions?.cases?.length || 0} built-in · ${(config.executable_task_packages || []).length} factory`;
      renderFactoryRepos();
    }

    function configPayload() {
      return {
        timeout_sec: Number($("cfgTimeout").value || 120),
        max_tokens: Number($("cfgMaxTokens").value || 200000),
        build_target: $("cfgBuildTarget").value || "assembleHap",
        run_build: $("cfgRunBuild").checked,
        require_model_lock: $("cfgRequireModelLock").checked,
        required_model: $("cfgRequiredModel").value.trim() || null,
        selected_model: selectedModel() || null,
        factory_repos: state.config?.factory_repos || [],
        executable_task_packages: state.config?.executable_task_packages || []
      };
    }

    function renderFactoryRepos() {
      const list = $("factoryRepoList");
      if (!list || !state.config) return;
      list.innerHTML = "";
      const repos = state.config.factory_repos || [];
      if (!repos.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No repositories configured.";
        list.appendChild(empty);
        return;
      }
      for (const repo of repos) {
        const item = document.createElement("div");
        item.className = "repo-item";
        item.innerHTML = `<div class="mono-line"></div><button type="button"></button>`;
        item.children[0].textContent = repo;
        item.querySelector("button").textContent = t("remove");
        item.querySelector("button").addEventListener("click", async () => {
          state.config.factory_repos = repos.filter(value => value !== repo);
          await saveConfig();
        });
        list.appendChild(item);
      }
    }

    function renderModels(models) {
      state.models = models || [];
      const select = $("modelSelect");
      const current = state.config?.selected_model || select.value;
      select.innerHTML = "";
      const fallback = document.createElement("option");
      fallback.value = "";
      fallback.textContent = t("defaultModel");
      select.appendChild(fallback);
      for (const model of state.models) {
        const option = document.createElement("option");
        option.value = model.id;
        option.textContent = `${model.label || model.id} · ${model.provider || "unknown"}`;
        select.appendChild(option);
      }
      select.value = state.models.some(model => model.id === current) ? current : "";
      if (state.config) state.config.selected_model = select.value || null;
    }

    function renderConditions() {
      const grid = $("conditionsGrid");
      if (!grid) return;
      grid.innerHTML = "";
      if (!state.conditions) {
        grid.innerHTML = `<div class="empty">${t("checking")}</div>`;
        return;
      }
      const items = [
        ["prompt", t("promptTemplate"), t("fixedPrompt"), state.conditions.prompt],
        ["environment", t("envVars"), t("fixedEnv"), state.conditions.environment],
        ["budget", t("budget"), t("fixedBudget"), state.conditions.budget],
        ["patch", t("patchRule"), t("fixedPatch"), state.conditions.patch],
        ["evaluation", t("evalSet"), t("fixedEval"), { evaluation: state.conditions.evaluation, cases: state.conditions.cases }],
        ["model_lock", t("modelLock"), t("fixedModel"), state.conditions.model_lock],
        ["build", t("buildValidation"), state.conditions.evaluation?.build?.target || "assembleHap", state.conditions.evaluation?.build],
        ["cases", t("cases"), `${state.conditions.cases?.length || 0} cases`, state.conditions.cases],
        ["benchmark_factory", t("factoryTitle"), `${state.conditions.benchmark_factory?.generated_tasks?.length || 0} generated`, state.conditions.benchmark_factory]
      ];
      for (const [key, title, summary, detail] of items) {
        const card = document.createElement("div");
        card.className = "condition-card";
        card.innerHTML = `
          <div class="condition-title"></div>
          <div class="condition-summary"></div>
          <button type="button"></button>
        `;
        card.querySelector(".condition-title").textContent = title;
        card.querySelector(".condition-summary").textContent = summary;
        card.querySelector("button").textContent = t("viewDetail");
        card.querySelector("button").addEventListener("click", () => showDetail(title, detail));
        grid.appendChild(card);
      }
    }

    function renderFactory() {
      const list = $("factoryList");
      if (!list) return;
      const factory = state.factory;
      const tasks = factory?.tasks || [];
      const executable = state.config?.executable_task_packages || [];
      $("mFactoryTasks").textContent = String(tasks.length);
      $("mFactoryRepos").textContent = String(factory?.repos?.length || 0);
      $("mExecSet").textContent = String(executable.length);
      $("mFactoryOutput").textContent = factory?.output_root || t("none");
      list.innerHTML = "";
      if (!tasks.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = t("emptyFactory");
        list.appendChild(empty);
        return;
      }
      for (const task of tasks) {
        const item = document.createElement("div");
        item.className = "factory-item";
        item.innerHTML = `
          <strong></strong>
          <span></span>
          <span></span>
          <button class="add-one" type="button"></button>
          <button type="button"></button>
        `;
        item.children[0].textContent = task.instance_id;
        item.children[1].textContent = task.task_type;
        item.children[2].textContent = `${task.difficulty || "n/a"} · ${(task.tags || []).slice(0, 3).join(", ")}`;
        item.querySelector(".add-one").textContent = executable.includes(task.package) ? "✓" : "+";
        item.querySelector(".add-one").addEventListener("click", async () => {
          await addTaskPackagesToSet([task.package]);
        });
        const detailButton = item.querySelectorAll("button")[1];
        detailButton.textContent = t("viewDetail");
        detailButton.addEventListener("click", async () => {
          try {
            const detail = await requestJson(`/api/benchmark-factory/task?package=${encodeURIComponent(task.package)}`);
            showDetail(task.instance_id, detail.task);
          } catch (error) {
            showDetail(task.instance_id, task);
          }
        });
        list.appendChild(item);
      }
    }

    function showDetail(title, value) {
      $("modalTitle").textContent = title;
      const pre = document.createElement("pre");
      pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      $("modalBody").replaceChildren(pre);
      $("detailModal").classList.add("open");
      $("closeModalBtn").focus();
    }

    function closeDetail() {
      $("detailModal").classList.remove("open");
    }

    function renderHarnesses(items, results = null) {
      state.harnesses = items || [];
      const grid = $("harnessGrid");
      grid.innerHTML = "";
      $("mHarnessCount").textContent = String(state.harnesses.length);
      for (const item of state.harnesses) {
        const result = results && results[item.name] ? results[item.name] : null;
        const status = result ? result.status : item.status;
        const score = result ? displayValue(result.score) : t("noResults");
        const passed = result ? `${result.passed}/${result.total}` : t("noResults");
        const issue = result?.rows?.find(row => row.probe && row.probe.reason)?.probe?.reason || item.issue || t("none");
        const card = document.createElement("div");
        card.className = "harness-card";
        card.innerHTML = `
          <div class="harness-head">
            <div>
              <div class="harness-name"></div>
              <div class="harness-desc"></div>
            </div>
            <span class="badge ${badgeClass(status)}"></span>
          </div>
          <div class="kv"><span></span><strong class="score"></strong></div>
          <div class="kv"><span></span><strong class="passed"></strong></div>
          <div class="kv"><span></span><strong class="model"></strong></div>
          <div class="kv"><span></span><strong class="issue"></strong></div>
          <div class="mono-line command"></div>
          <div class="harness-actions"><button class="run-model" type="button"></button><button class="debug-harness" type="button"></button></div>
        `;
        const labels = card.querySelectorAll(".kv span");
        labels[0].textContent = t("score");
        labels[1].textContent = t("passed");
        labels[2].textContent = t("modelLabel");
        labels[3].textContent = t("issue");
        card.querySelector(".harness-name").textContent = item.label;
        card.querySelector(".harness-desc").textContent = item.description;
        card.querySelector(".badge").textContent = status;
        card.querySelector(".score").textContent = score;
        card.querySelector(".passed").textContent = passed;
        card.querySelector(".model").textContent = item.model_lock || "fixed by harness/config";
        card.querySelector(".issue").textContent = issue;
        card.querySelector(".command").textContent = item.command;
        card.querySelector(".run-model").textContent = t("runModel");
        card.querySelector(".run-model").addEventListener("click", () => runHarness(item.name));
        const debugButton = card.querySelector(".debug-harness");
        debugButton.textContent = t("debugHarness");
        debugButton.style.display = item.name === "bitfun" ? "" : "none";
        debugButton.addEventListener("click", () => debugHarness(item.name));
        grid.appendChild(card);
      }
    }

    function renderDoctor(data) {
      $("toolList").innerHTML = "";
      let okCount = 0;
      for (const tool of data.tools) {
        if (tool.status === "ok") okCount += 1;
        const item = document.createElement("div");
        item.className = "tool";
        const badge = document.createElement("div");
        badge.className = "badge " + tool.status;
        badge.textContent = tool.status;
        const body = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = tool.name + (tool.version ? " · " + tool.version : "");
        const path = document.createElement("div");
        path.className = "tool-path";
        path.textContent = tool.error ? tool.path + " · " + tool.error : tool.path;
        body.append(title, path);
        item.append(badge, body);
        $("toolList").appendChild(item);
      }
      const total = data.tools.length;
      $("toolSummary").textContent = okCount === total ? `Ready ${okCount}/${total}` : `${t("needsAttention")} ${okCount}/${total}`;
    }

    function renderResult(data) {
      state.result = data;
      $("mArtifacts").textContent = data.artifact_dir || t("none");
      const harnesses = data.summary?.harnesses || {};
      const scores = Object.values(harnesses).map(item => item.score).filter(value => typeof value === "number");
      $("mBestScore").textContent = scores.length ? String(Math.max(...scores)) : "n/a";
      $("mTokens").textContent = displayTokens(data.summary?.token_usage);
      renderResultsTable();
      renderTab();
    }

    function renderHistory(entries) {
      const list = $("historyList");
      list.innerHTML = "";
      if (!entries || entries.length === 0) {
        list.innerHTML = `<div class="empty">${t("emptyHistory")}</div>`;
        return;
      }
      for (const entry of entries) {
        const harnessNames = Object.keys(entry.harnesses || {});
        const scores = harnessNames.map(name => {
          const item = entry.harnesses[name] || {};
          return `${name}: ${displayValue(item.score)} (${displayValue(item.passed)}/${displayValue(item.total)})`;
        }).join(" · ");
        const item = document.createElement("div");
        item.className = "history-item";
        item.innerHTML = `
          <div><div class="history-title"></div><div class="history-meta"></div></div>
          <div class="history-meta"></div>
          <div class="history-meta"></div>
          <div class="history-meta"></div>
          <button class="detail-link" type="button"></button>
        `;
        item.querySelector(".history-title").textContent = entry.label || entry.history_id;
        item.querySelector(".history-meta").textContent = scores || t("none");
        item.children[1].textContent = entry.created_at ? new Date(entry.created_at).toLocaleString() : "n/a";
        item.children[2].textContent = displayTokens(entry.token_usage);
        item.children[3].textContent = entry.artifacts_root || t("none");
        item.querySelector("button").textContent = t("viewDetail");
        item.querySelector("button").addEventListener("click", () => showDetail(entry.label || entry.history_id, entry));
        list.appendChild(item);
      }
    }

    function renderResultsTable() {
      const view = $("resultsView");
      const harnesses = state.result?.summary?.harnesses;
      if (!harnesses) {
        view.className = "empty";
        view.textContent = t("emptyResults");
        return;
      }
      view.className = "";
      const table = document.createElement("table");
      table.className = "results-table";
      table.innerHTML = `
        <thead><tr>
          <th>${t("harness")}</th><th>${t("status")}</th><th>${t("score")}</th><th>${t("passed")}</th><th>${t("tokenUsage")}</th><th>${t("issue")}</th>
        </tr></thead>
        <tbody></tbody>
      `;
      const body = table.querySelector("tbody");
      for (const [name, result] of Object.entries(harnesses)) {
        const issue = result.rows?.find(row => row.probe && row.probe.reason)?.probe?.reason || t("none");
        const row = document.createElement("tr");
        row.innerHTML = `
          <td><strong></strong></td>
          <td><span class="badge ${badgeClass(result.status)}"></span></td>
          <td><button class="detail-link score-detail" type="button"></button></td>
          <td></td>
          <td></td>
          <td></td>
        `;
        row.querySelector("strong").textContent = name;
        row.querySelector(".badge").textContent = result.status;
        row.querySelector(".score-detail").textContent = displayValue(result.score);
        row.querySelector(".score-detail").addEventListener("click", () => showDetail(`${name} ${t("score")}`, result));
        row.children[3].textContent = `${result.passed}/${result.total}`;
        row.children[4].textContent = displayTokens(result.token_usage);
        row.children[5].textContent = issue;
        body.appendChild(row);
        for (const caseResult of result.rows || []) {
          const caseRow = document.createElement("tr");
          caseRow.className = "case-row";
          caseRow.innerHTML = `
            <td></td>
            <td><span class="badge ${badgeClass(caseResult.status)}"></span></td>
            <td><button class="detail-link case-detail" type="button"></button></td>
            <td></td>
            <td></td>
            <td></td>
          `;
          caseRow.children[0].textContent = caseResult.title || caseResult.instance_id;
          caseRow.querySelector(".badge").textContent = caseResult.status;
          caseRow.querySelector(".case-detail").textContent = displayValue(caseResult.score);
          caseRow.querySelector(".case-detail").addEventListener("click", () => showDetail(caseResult.instance_id, caseResult));
          caseRow.children[3].textContent = caseResult.passed ? "1/1" : "0/1";
          caseRow.children[4].textContent = displayTokens(caseResult.token_usage);
          caseRow.children[5].textContent = caseResult.probe?.reason || caseResult.build?.reason || t("none");
          body.appendChild(caseRow);
        }
      }
      view.replaceChildren(table);
    }

    function renderTab() {
      const output = $("output");
      if (state.detail) {
        const pre = document.createElement("pre");
        pre.textContent = state.detail.title + "\\n" + JSON.stringify(state.detail.value, null, 2);
        output.className = "";
        output.replaceChildren(pre);
        return;
      }
      if (!state.result) {
        output.className = "empty";
        output.textContent = t("emptyOutput");
        return;
      }
      const value = state.result[state.tab] || "";
      const pre = document.createElement("pre");
      pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      output.className = "";
      output.replaceChildren(pre);
    }

    async function refreshHarnesses() {
      try {
        const data = await requestJson("/api/harnesses");
        renderHarnesses(data.harnesses, state.result?.summary?.harnesses || null);
      } catch (error) {
        $("statusLine").textContent = error.message;
      }
    }

    async function refreshModels() {
      try {
        const data = await requestJson("/api/models");
        renderModels(data.models);
      } catch (error) {
        $("statusLine").textContent = error.message;
      }
    }

    async function loadConfig() {
      try {
        const data = await requestJson("/api/gui-config");
        state.config = data.config;
        renderConfig();
      } catch (error) {
        $("statusLine").textContent = error.message;
      }
    }

    async function saveConfig() {
      const payload = configPayload();
      payload.factory_repos = state.config?.factory_repos || [];
      payload.executable_task_packages = state.config?.executable_task_packages || [];
      const data = await requestJson("/api/gui-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      state.config = data.config;
      renderConfig();
      $("statusLine").textContent = t("configSaved");
      return data.config;
    }

    async function loadConditions() {
      try {
        state.conditions = await requestJson("/api/evaluation-conditions");
        renderConditions();
      } catch (error) {
        $("statusLine").textContent = error.message;
      }
    }

    async function refreshHistory() {
      try {
        const data = await requestJson("/api/history");
        renderHistory(data.history);
      } catch (error) {
        $("statusLine").textContent = error.message;
      }
    }

    async function refreshFactory() {
      try {
        const data = await requestJson("/api/benchmark-factory");
        state.factory = data.factory;
        renderFactory();
      } catch (error) {
        $("statusLine").textContent = error.message;
      }
    }

    async function runFactory() {
      setBusy(true, "running");
      try {
        const data = await requestJson("/api/benchmark-factory", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repos: state.config?.factory_repos || [] })
        });
        state.factory = data.factory;
        renderFactory();
        showDetail(t("factoryTitle"), data.factory);
        $("statusLine").textContent = t("factoryDone");
      } catch (error) {
        $("statusLine").textContent = error.message;
      } finally {
        for (const button of document.querySelectorAll("button")) button.disabled = false;
      }
    }

    async function addRepo() {
      const value = $("factoryRepoInput").value.trim();
      if (!value) return;
      if (!state.config) await loadConfig();
      const repos = state.config.factory_repos || [];
      if (!repos.includes(value)) repos.push(value);
      state.config.factory_repos = repos;
      $("factoryRepoInput").value = "";
      await saveConfig();
    }

    async function addTaskPackagesToSet(packages) {
      if (!state.config) await loadConfig();
      const existing = new Set(state.config.executable_task_packages || []);
      for (const pkg of packages || []) {
        if (pkg) existing.add(pkg);
      }
      state.config.executable_task_packages = Array.from(existing);
      await saveConfig();
      renderFactory();
      $("statusLine").textContent = t("addedGenerated");
    }

    async function addGeneratedTasks() {
      const packages = (state.factory?.tasks || []).map(task => task.package);
      await addTaskPackagesToSet(packages);
    }

    async function runFactorySet() {
      if (!window.confirm(t("confirmRunFactorySet"))) return;
      setBusy(true, "running");
      try {
        const data = await requestJson("/api/factory-test-set/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: selectedModel() })
        });
        state.detail = null;
        renderResult(data);
        if (data.harnesses) renderHarnesses(data.harnesses, data.summary.harnesses);
        state.tab = "benchmark";
        for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("active", tab.dataset.tab === state.tab);
        renderTab();
        refreshHistory();
        $("statusLine").textContent = t("factorySetDone");
      } catch (error) {
        $("statusLine").textContent = error.message;
      } finally {
        for (const button of document.querySelectorAll("button")) button.disabled = false;
      }
    }

    async function runDoctor() {
      setBusy(true, "checking");
      $("toolSummary").textContent = t("checking");
      $("toolList").innerHTML = "";
      try {
        renderDoctor(await requestJson("/api/doctor", { method: "POST" }));
        $("statusLine").textContent = t("checked");
      } catch (error) {
        $("toolSummary").textContent = "Failed";
        $("statusLine").textContent = error.message;
      } finally {
        for (const button of document.querySelectorAll("button")) button.disabled = false;
      }
    }

    async function runBenchmark() {
      setBusy(true, "running");
      try {
        const data = await requestJson("/api/benchmark-demo", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: selectedModel() })
        });
        state.detail = null;
        renderResult(data);
        if (data.harnesses) renderHarnesses(data.harnesses, data.summary.harnesses);
        state.tab = "benchmark";
        for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("active", tab.dataset.tab === state.tab);
        renderTab();
        refreshHistory();
        $("statusLine").textContent = t("benchmarkDone");
      } catch (error) {
        $("statusLine").textContent = error.message;
      } finally {
        for (const button of document.querySelectorAll("button")) button.disabled = false;
      }
    }

    async function runHarness(name) {
      if (!window.confirm(t("confirmRunModel"))) return;
      setBusy(true, "running");
      try {
        const data = await requestJson("/api/benchmark-harness", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ harness: name, model: selectedModel() })
        });
        state.detail = null;
        renderResult(data);
        if (data.harnesses) renderHarnesses(data.harnesses, data.summary.harnesses);
        state.tab = "benchmark";
        for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("active", tab.dataset.tab === state.tab);
        renderTab();
        refreshHistory();
        $("statusLine").textContent = t("harnessDone");
      } catch (error) {
        $("statusLine").textContent = error.message;
      } finally {
        for (const button of document.querySelectorAll("button")) button.disabled = false;
      }
    }

    async function debugHarness(name) {
      if (name !== "bitfun") return;
      if (!window.confirm(t("confirmDebugHarness"))) return;
      setBusy(true, "running");
      try {
        const data = await requestJson("/api/bitfun-debug", { method: "POST" });
        showDetail("BitFun Debug", data);
        $("statusLine").textContent = t("debugDone");
      } catch (error) {
        $("statusLine").textContent = error.message;
      } finally {
        for (const button of document.querySelectorAll("button")) button.disabled = false;
      }
    }

    async function runDemo() {
      setBusy(true, "running");
      try {
        const data = await requestJson("/api/demo", { method: "POST" });
        state.detail = null;
        renderResult(data);
        $("statusLine").textContent = t("taskDone");
      } catch (error) {
        $("statusLine").textContent = error.message;
      } finally {
        for (const button of document.querySelectorAll("button")) button.disabled = false;
      }
    }

    async function loadDemoValues() {
      setBusy(true, "running");
      try {
        const data = await requestJson("/api/demo-setup", { method: "POST" });
        $("instanceId").value = data.instance_id;
        $("runId").value = data.run_id;
        $("repo").value = data.repo;
        $("instruction").value = data.instruction;
        $("harnessCommand").value = data.harness_command;
        $("artifactsRoot").value = data.artifacts_root;
        $("model").value = data.model;
        $("timeoutSec").value = data.timeout_sec;
        $("maxTokens").value = data.max_tokens || "";
        $("evaluationCriteria").value = data.evaluation_criteria;
        $("statusLine").textContent = t("demoLoaded");
      } catch (error) {
        $("statusLine").textContent = error.message;
      } finally {
        for (const button of document.querySelectorAll("button")) button.disabled = false;
      }
    }

    async function runCustom() {
      const body = {
        instance_id: $("instanceId").value,
        run_id: $("runId").value,
        repo: $("repo").value,
        instruction: $("instruction").value,
        harness_command: $("harnessCommand").value,
        artifacts_root: $("artifactsRoot").value,
        model: $("model").value,
        timeout_sec: $("timeoutSec").value,
        max_tokens: $("maxTokens").value,
        evaluation_criteria: $("evaluationCriteria").value
      };
      setBusy(true, "running");
      try {
        const data = await requestJson("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });
        state.detail = null;
        renderResult(data);
        $("statusLine").textContent = t("taskDone");
      } catch (error) {
        $("statusLine").textContent = error.message;
      } finally {
        for (const button of document.querySelectorAll("button")) button.disabled = false;
      }
    }

    for (const tab of document.querySelectorAll(".tab")) {
      tab.addEventListener("click", () => {
        state.detail = null;
        state.tab = tab.dataset.tab;
        for (const item of document.querySelectorAll(".tab")) item.classList.toggle("active", item === tab);
        renderTab();
      });
    }
    $("conditionsJsonBtn").addEventListener("click", () => showDetail(t("conditions"), state.conditions || {}));
    $("factoryBtn").addEventListener("click", runFactory);
    $("factoryDetailBtn").addEventListener("click", () => showDetail(t("factoryTitle"), state.factory || {}));
    $("saveConfigBtn").addEventListener("click", async () => {
      try { await saveConfig(); } catch (error) { $("statusLine").textContent = error.message; }
    });
    $("addRepoBtn").addEventListener("click", async () => {
      try { await addRepo(); } catch (error) { $("statusLine").textContent = error.message; }
    });
    $("addGeneratedBtn").addEventListener("click", async () => {
      try { await addGeneratedTasks(); } catch (error) { $("statusLine").textContent = error.message; }
    });
    $("runFactorySetBtn").addEventListener("click", runFactorySet);
    $("closeModalBtn").addEventListener("click", closeDetail);
    $("detailModal").addEventListener("click", (event) => {
      if (event.target === $("detailModal")) closeDetail();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDetail();
    });
    $("langZh").addEventListener("click", () => { state.lang = "zh"; localStorage.setItem("harmonyAdapterLang", state.lang); applyLanguage(); });
    $("langEn").addEventListener("click", () => { state.lang = "en"; localStorage.setItem("harmonyAdapterLang", state.lang); applyLanguage(); });
    $("doctorBtn").addEventListener("click", runDoctor);
    $("refreshHarnessBtn").addEventListener("click", refreshHarnesses);
    $("refreshHistoryBtn").addEventListener("click", refreshHistory);
    $("benchmarkBtn").addEventListener("click", runBenchmark);
    $("runBtn").addEventListener("click", runCustom);
    $("loadDemoBtn").addEventListener("click", loadDemoValues);
    $("demoBtn").addEventListener("click", runDemo);
    applyLanguage();
    loadConfig();
    loadConditions();
    refreshFactory();
    refreshHarnesses();
    refreshModels();
    refreshHistory();
    runDoctor();
  </script>
</body>
</html>
"""


class GuiHandler(BaseHTTPRequestHandler):
    server_version = "HarmonyAdapterGUI/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._send_html(HTML)
            return
        if path == "/api/doctor":
            self._send_json(self._doctor())
            return
        if path == "/api/harnesses":
            self._send_json({"harnesses": _harness_catalog()})
            return
        if path == "/api/models":
            self._send_json({"models": _model_catalog()})
            return
        if path == "/api/evaluation-conditions":
            self._send_json(_evaluation_conditions())
            return
        if path == "/api/history":
            self._send_json({"history": read_evaluation_history()})
            return
        if path == "/api/gui-config":
            self._send_json({"config": _read_gui_config()})
            return
        if path == "/api/benchmark-factory":
            self._send_json({"factory": _read_factory_summary()})
            return
        if path == "/api/benchmark-factory/task":
            package = parse_qs(parsed.query).get("package", [""])[0]
            self._send_json({"task": _read_factory_task(package)})
            return
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        routes = {
            "/api/doctor": self._doctor,
            "/api/demo": self._demo,
            "/api/demo-setup": self._demo_setup,
            "/api/harnesses": lambda: {"harnesses": _harness_catalog()},
            "/api/models": lambda: {"models": _model_catalog()},
            "/api/history": lambda: {"history": read_evaluation_history()},
            "/api/gui-config": self._save_gui_config,
            "/api/evaluation-conditions": _evaluation_conditions,
            "/api/benchmark-factory": self._benchmark_factory,
            "/api/bitfun-debug": self._bitfun_debug,
            "/api/factory-test-set/run": self._factory_test_set_run,
            "/api/benchmark-demo": self._benchmark_demo,
            "/api/benchmark-harness": self._benchmark_harness,
            "/api/run": self._run,
        }
        handler = routes.get(self.path)
        if not handler:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            self._send_json(handler())
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _doctor(self) -> dict[str, Any]:
        config = HarmonyConfig.from_env()
        adapter = HarmonyAdapter(config)
        tools = []
        for check in adapter.toolchain.checks():
            if not check.exists:
                status = "missing"
            elif check.error:
                status = "error"
            else:
                status = "ok"
            tools.append(
                {
                    "name": check.name,
                    "path": str(check.path),
                    "status": status,
                    "version": check.version,
                    "error": check.error,
                }
            )
        return {
            "sdk_home": str(config.sdk_home),
            "node_home": str(config.node_home),
            "device_id": config.device_id,
            "tools": tools,
        }

    def _demo_setup(self) -> dict[str, Any]:
        return _prepare_demo()

    def _demo(self) -> dict[str, Any]:
        demo = _prepare_demo()
        return _run_adapter(demo)

    def _benchmark_demo(self) -> dict[str, Any]:
        payload = self._read_json()
        artifacts_root = Path(tempfile.mkdtemp(prefix="harmony-benchmark-gui-")) / "artifacts"
        return _benchmark_response(default_harnesses(), artifacts_root=artifacts_root, instance_id="benchmark-demo", model=_selected_model(payload))

    def _benchmark_harness(self) -> dict[str, Any]:
        payload = self._read_json()
        name = str(payload.get("harness", "")).strip().lower()
        harnesses_by_name = {
            "codex": codex_harness(),
            "bitfun": bitfun_harness(),
        }
        if name not in harnesses_by_name:
            raise ValueError("Unsupported harness. Expected one of: codex, bitfun")
        artifacts_root = Path(tempfile.mkdtemp(prefix=f"harmony-benchmark-{name}-gui-")) / "artifacts"
        return _benchmark_response(harnesses_by_name[name], artifacts_root=artifacts_root, instance_id=f"{name}-benchmark", model=_selected_model(payload))

    def _run(self) -> dict[str, Any]:
        payload = self._read_json()
        return _run_adapter(payload)

    def _benchmark_factory(self) -> dict[str, Any]:
        payload = self._read_json()
        gui_config = _read_gui_config()
        output_root = Path(str(payload.get("output_root") or Path("artifacts") / "benchmark-factory"))
        cache_root = Path(str(payload.get("cache_root") or Path("artifacts") / "seed-repos"))
        online = bool(payload.get("online", False))
        repo_values = payload.get("repos") or gui_config.get("factory_repos") or []
        repos = [Path(str(repo)) for repo in repo_values if str(repo).strip()]
        seeds: list[dict[str, Any]] = []
        if not repos:
            materialized = materialize_default_seed_repos(cache_root, online=online)
            repos = materialized["repos"]
            seeds = materialized["seeds"]
        summary = generate_factory(repos, output_root=output_root, max_tasks_per_repo=int(payload.get("max_tasks_per_repo") or 4))
        summary["seeds"] = seeds
        write_json(output_root / "factory_summary.json", summary)
        return {"factory": summary}

    def _bitfun_debug(self) -> dict[str, Any]:
        return _bitfun_debug()

    def _save_gui_config(self) -> dict[str, Any]:
        return {"config": _write_gui_config(self._read_json())}

    def _factory_test_set_run(self) -> dict[str, Any]:
        payload = self._read_json()
        return _factory_test_set_response(model=_selected_model(payload))

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _send_html(self, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _benchmark_response(harnesses: dict[str, str], artifacts_root: Path, instance_id: str, model: str | None = None) -> dict[str, Any]:
    gui_config = _read_gui_config()
    from harmony_adapter.evaluation import EvaluationOptions

    summary = run_benchmark(
        harnesses,
        artifacts_root=artifacts_root,
        timeout_sec=int(gui_config.get("timeout_sec") or 120),
        max_tokens=int(gui_config.get("max_tokens") or 200000),
        required_model=gui_config.get("required_model"),
        require_model_lock=bool(gui_config.get("require_model_lock")),
        selected_model=model or gui_config.get("selected_model"),
        evaluation_options=EvaluationOptions(
            run_build=bool(gui_config.get("run_build")),
            build_target=str(gui_config.get("build_target") or "assembleHap"),
            build_timeout_sec=int(gui_config.get("build_timeout_sec") or 300),
        ),
    )
    history_entry = append_evaluation_history(summary, label=instance_id, trigger="gui")
    leaderboard = []
    for name, result in summary["harnesses"].items():
        leaderboard.append(
            {
                "harness": name,
                "status": result["status"],
                "passed": result["passed"],
                "total": result["total"],
                "pass_rate": result["pass_rate"],
                "score": result["score"],
            }
        )
    benchmark_text = json.dumps({"leaderboard": leaderboard, "summary": summary}, ensure_ascii=False, indent=2)
    return {
        "instance_id": instance_id,
        "exit_code": 0,
        "patch_bytes": 0,
        "artifact_dir": str(artifacts_root),
        "patch": "Benchmark demo runs multiple tasks; inspect the Benchmark tab for scored results.",
        "metadata": benchmark_text,
        "contract": "Built-in benchmark uses fixed prompts, fixed adapter environment, timeout/token budget, runner-side patch extraction, patch-scope checks, optional Harmony build validation, and model-lock probes.",
        "contract_json": {
            "prompt_policy": "adapter rendered per case",
            "budget": {"timeout_sec": 120, "max_turns": None, "max_tokens": 200000},
            "patch_policy": "runner-side git diff --binary per case",
            "evaluation_criteria": "oracle checks + unrelated edit detection + Harmony build validation when build metadata exists",
            "environment": {"exported_keys": ["DEVECO_SDK_HOME", "HARMONY_MAX_TOKENS", "HARMONY_TIMEOUT_SEC", "NODE_HOME", "PATH"]},
            "model_lock": {"required_model": None, "required_variant": None, "require_model_lock": False, "selected_model": model},
        },
        "stdout": "",
        "stderr": "",
        "prompt": "",
        "benchmark": benchmark_text,
        "summary": summary,
        "history_entry": history_entry,
        "harnesses": _harness_catalog(),
    }


def _factory_test_set_response(model: str | None = None) -> dict[str, Any]:
    gui_config = _read_gui_config()
    packages = [Path(path) for path in gui_config.get("executable_task_packages", [])]
    if not packages:
        raise ValueError("Executable test set is empty. Add generated task packages first.")
    harnesses = default_harnesses()
    artifacts_root = Path(tempfile.mkdtemp(prefix="harmony-factory-test-set-gui-")) / "artifacts"
    summary: dict[str, Any] = {
        "benchmark_root": None,
        "artifacts_root": str(artifacts_root),
        "case_count": len(packages),
        "evaluation_mode": {
            "source": "Benchmark Factory executable task set",
            "oracle": "Task package execution summary; hidden reference oracles are packaged for later validators.",
            "config": gui_config,
        },
        "harnesses": {},
    }
    for harness_name, harness_command in harnesses.items():
        rows = []
        passed = 0
        config = HarmonyConfig.from_env()
        config = HarmonyConfig(
            dev_eco_home=config.dev_eco_home,
            sdk_home=config.sdk_home,
            node_home=config.node_home,
            ohpm_bin=config.ohpm_bin,
            hvigor_bin=config.hvigor_bin,
            hdc_bin=config.hdc_bin,
            device_id=config.device_id,
            harness_command=harness_command,
            timeout_sec=int(gui_config.get("timeout_sec") or 120),
            max_tokens=int(gui_config.get("max_tokens") or 200000),
            required_model=gui_config.get("required_model"),
            require_model_lock=bool(gui_config.get("require_model_lock")),
            model_name=model or gui_config.get("selected_model") or harness_name,
            actual_model=model or gui_config.get("selected_model"),
            artifacts_root=artifacts_root,
            evaluation_criteria="Run generated Harmony SWE-type task package and collect runner-side patch.",
        )
        adapter = HarmonyAdapter(config)
        for package in packages:
            task_data = _read_factory_task(str(package))
            task = TaskSpec(
                instance_id=str(task_data["instance_id"]),
                repo=Path(str(task_data["repo"])),
                instruction=str(task_data["problem_statement"]),
                base_commit=str(task_data.get("base_commit") or "") or None,
                metadata={"task_package": str(package), "task_type": task_data.get("task_type")},
            )
            record = adapter.run_task(task, run_id=f"factory-set-{harness_name}")
            artifact_dir = Path(str(record.metadata["artifact_dir"]))
            ok = int(record.metadata["exit_code"]) == 0 and bool(record.model_patch.strip())
            passed += 1 if ok else 0
            rows.append(
                {
                    "instance_id": task.instance_id,
                    "title": f"{task_data.get('task_type')} · {task.instance_id}",
                    "status": "ran" if record.metadata["exit_code"] == 0 else "error",
                    "passed": ok,
                    "score": 1.0 if ok else 0.0,
                    "exit_code": record.metadata["exit_code"],
                    "patch_bytes": len(record.model_patch.encode("utf-8")),
                    "artifact_dir": str(artifact_dir),
                    "task_package": str(package),
                    "details": task_data.get("hidden_validation", {}),
                    "probe": {},
                    "token_usage": {"total": None, "source": "unavailable"},
                }
            )
        total = len(packages)
        summary["harnesses"][harness_name] = {
            "status": "scored",
            "passed": passed,
            "total": total,
            "pass_rate": round(passed / total, 3) if total else None,
            "score": round(passed / total, 3) if total else None,
            "token_usage": {"total": None, "source": "unavailable"},
            "rows": rows,
        }
    summary["token_usage"] = {"total": None, "source": "unavailable"}
    write_json(artifacts_root / "factory_test_set_summary.json", summary)
    history_entry = append_evaluation_history(summary, label="factory-test-set", trigger="gui")
    benchmark_text = json.dumps({"summary": summary}, ensure_ascii=False, indent=2)
    return {
        "instance_id": "factory-test-set",
        "exit_code": 0,
        "patch_bytes": 0,
        "artifact_dir": str(artifacts_root),
        "patch": "Factory test set run; inspect per-case artifact directories.",
        "metadata": benchmark_text,
        "contract": "Generated Task Packages are executed with saved GUI control settings.",
        "contract_json": {"config": gui_config, "packages": [str(path) for path in packages]},
        "stdout": "",
        "stderr": "",
        "prompt": "",
        "benchmark": benchmark_text,
        "summary": summary,
        "history_entry": history_entry,
        "harnesses": _harness_catalog(),
    }


def _default_gui_config() -> dict[str, Any]:
    return {
        "timeout_sec": 120,
        "max_tokens": 200000,
        "run_build": True,
        "build_target": "assembleHap",
        "build_timeout_sec": 300,
        "require_model_lock": False,
        "required_model": None,
        "selected_model": None,
        "factory_repos": _discover_seed_repos(),
        "executable_task_packages": [],
    }


def _read_gui_config() -> dict[str, Any]:
    config = _default_gui_config()
    if GUI_CONFIG_PATH.exists():
        try:
            stored = json.loads(GUI_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                config.update(stored)
        except json.JSONDecodeError:
            pass
    config["factory_repos"] = [
        str(Path(repo)) for repo in config.get("factory_repos", []) if str(repo).strip() and _is_valid_git_repo(Path(str(repo)))
    ]
    config["executable_task_packages"] = [
        str(Path(package)) for package in config.get("executable_task_packages", []) if str(package).strip()
    ]
    return config


def _write_gui_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = _read_gui_config()
    editable = {
        "timeout_sec": int(payload.get("timeout_sec") or current["timeout_sec"]),
        "max_tokens": int(payload.get("max_tokens") or current["max_tokens"]),
        "run_build": bool(payload.get("run_build", current["run_build"])),
        "build_target": str(payload.get("build_target") or current["build_target"]),
        "build_timeout_sec": int(payload.get("build_timeout_sec") or current["build_timeout_sec"]),
        "require_model_lock": bool(payload.get("require_model_lock", current["require_model_lock"])),
        "required_model": str(payload.get("required_model") or "").strip() or None,
        "selected_model": str(payload.get("selected_model") or "").strip() or None,
        "factory_repos": _unique_strings(payload.get("factory_repos", current["factory_repos"])),
        "executable_task_packages": _unique_strings(payload.get("executable_task_packages", current["executable_task_packages"])),
    }
    write_json(ensure_parent(GUI_CONFIG_PATH), editable)
    return editable


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _unique_strings(values: Any) -> list[str]:
    seen = set()
    result = []
    if not isinstance(values, list):
        return result
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _discover_seed_repos() -> list[str]:
    root = Path("artifacts") / "seed-repos"
    if not root.exists():
        return []
    return [str(path) for path in sorted(root.iterdir()) if _is_valid_git_repo(path)]


def _is_valid_git_repo(path: Path) -> bool:
    if not (path / ".git").exists():
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
        check=False,
    )
    return result.returncode == 0


def _read_factory_summary() -> dict[str, Any]:
    path = Path("artifacts") / "benchmark-factory" / "factory_summary.json"
    if not path.exists():
        return {
            "output_root": str(path.parent),
            "repos": [],
            "tasks": [],
            "quality_gates": ["Base-Fail", "Patch-Pass", "Leakage Check", "Hidden Oracle", "Manual Audit"],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _read_factory_task(package: str) -> dict[str, Any]:
    path = Path(package).resolve()
    allowed_root = (Path.cwd() / "artifacts" / "benchmark-factory" / "tasks").resolve()
    if path.name != "task.json" or allowed_root not in path.parents:
        raise ValueError("Invalid factory task package path")
    if not path.exists():
        raise ValueError("Factory task package not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _prepare_demo() -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="harmony-adapter-gui-"))
    repo = root / "repo"
    tools = root / "tools"
    artifacts = root / "artifacts"
    repo.mkdir()
    tools.mkdir()
    artifacts.mkdir()

    (repo / "App.ets").write_text("ability: pending\n", encoding="utf-8")
    _run_cmd(["git", "init"], repo)
    _run_cmd(["git", "config", "user.email", "adapter-demo@example.test"], repo)
    _run_cmd(["git", "config", "user.name", "Harmony Adapter Demo"], repo)
    _run_cmd(["git", "add", "App.ets"], repo)
    _run_cmd(["git", "commit", "-m", "initial demo app"], repo)

    harness = tools / "fake_harness.py"
    harness.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import argparse",
                "parser = argparse.ArgumentParser()",
                "parser.add_argument('--prompt')",
                "parser.add_argument('--workspace')",
                "parser.add_argument('--artifacts')",
                "args = parser.parse_args()",
                "Path('App.ets').write_text('ability: implemented from GUI demo\\n', encoding='utf-8')",
                "Path(args.artifacts, 'harness_report.txt').write_text('GUI demo harness completed\\n', encoding='utf-8')",
                "print('GUI demo harness updated App.ets')",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "instance_id": "gui-demo-001",
        "run_id": "gui-demo",
        "repo": str(repo),
        "instruction": "把 App.ets 中的 ability 状态改成已实现。",
        "harness_command": f"python3 {harness} --prompt {{prompt}} --workspace {{workspace}} --artifacts {{artifacts}}",
        "artifacts_root": str(artifacts),
        "model": "gui-demo-model",
        "timeout_sec": 3600,
        "max_tokens": 200000,
        "evaluation_criteria": (
            "Harness-owned tests and reports decide pass/fail. The adapter records runner-side "
            "git diff as the accepted patch."
        ),
    }


def _harness_catalog() -> list[dict[str, Any]]:
    project_root = Path.cwd()
    bitfun_app = Path("/Applications/BitFun.app/Contents/MacOS/bitfun-desktop")
    bitfun_source = project_root / ".tools" / "BitFun"
    bitfun_source_cli = bitfun_source / "target" / "release" / "bitfun"
    bitfun_cli = os.environ.get("BITFUN_EXEC_BIN") or (str(bitfun_source_cli) if bitfun_source_cli.exists() else None) or shutil.which("bitfun")
    bitfun_probe = _bitfun_config_probe(bitfun_cli)
    codex_cli = os.environ.get("CODEX_EXEC_BIN") or shutil.which("codex") or "/Applications/ChatGPT.app/Contents/Resources/codex"
    codex_exists = Path(codex_cli).exists()
    codex_model = os.environ.get("CODEX_MODEL") or os.environ.get("HARMONY_REQUIRED_MODEL") or "unset"
    require_lock = os.environ.get("HARMONY_REQUIRE_MODEL_LOCK", "").lower() in {"1", "true", "yes", "on"}

    return [
        {
            "name": "codex",
            "label": "Codex",
            "status": "ready" if codex_exists and not (require_lock and codex_model == "unset") else "model_unlocked" if codex_exists else "missing",
            "description": "Local Codex CLI harness. Runs through `codex exec -C <workspace>` and lets the adapter collect the patch.",
            "command": codex_harness()["codex"],
            "model_lock": codex_model,
            "issue": "Model lock required but CODEX_MODEL/HARMONY_REQUIRED_MODEL is unset" if codex_exists and require_lock and codex_model == "unset" else "Codex CLI not found" if not codex_exists else "None",
            "tools": {"codex": codex_cli},
        },
        {
            "name": "bitfun",
            "label": "BitFun",
            "status": bitfun_probe["status"] if bitfun_cli else "unsupported",
            "description": "Local BitFun coding agent. Requires a headless `bitfun exec` compatible command to be scored automatically.",
            "command": bitfun_harness()["bitfun"],
            "model_lock": os.environ.get("BITFUN_MODEL") or os.environ.get("HARMONY_ACTUAL_MODEL") or ("required but unset" if require_lock else "inside BitFun config"),
            "issue": bitfun_probe["issue"] if bitfun_cli else "BitFun source is present, but CLI is not built" if bitfun_source.exists() and not bitfun_cli else "Desktop app found, but no `bitfun` CLI on PATH" if bitfun_app.exists() and not bitfun_cli else "BitFun desktop app not found" if not bitfun_app.exists() else "None",
            "tools": {"source": str(bitfun_source), "cli": bitfun_cli or str(bitfun_source_cli), "desktop": str(bitfun_app)},
        },
    ]


def _selected_model(payload: dict[str, Any]) -> str | None:
    value = str(payload.get("model", "")).strip()
    return value or None


def _model_catalog() -> list[dict[str, Any]]:
    models = []
    bitfun_cli = os.environ.get("BITFUN_EXEC_BIN") or str(Path.cwd() / ".tools" / "BitFun" / "target" / "release" / "bitfun")
    if Path(bitfun_cli).exists():
        models.extend(_bitfun_models(bitfun_cli))
    codex_model = os.environ.get("CODEX_MODEL") or os.environ.get("HARMONY_REQUIRED_MODEL")
    if codex_model:
        models.append({"id": codex_model, "label": codex_model, "provider": "codex", "harnesses": ["codex"]})
    seen = set()
    unique = []
    for model in models:
        if model["id"] in seen:
            continue
        seen.add(model["id"])
        unique.append(model)
    return unique


def _bitfun_models(bitfun_cli: str) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            [bitfun_cli, "models", "list"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    models = []
    current: dict[str, Any] | None = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            marker_removed = stripped[2:].strip()
            is_default = marker_removed.startswith("* ")
            model_id = marker_removed[2:].split(" ", 1)[0] if is_default else marker_removed.split(" ", 1)[0]
            current = {"id": model_id, "label": model_id, "provider": "bitfun", "harnesses": ["bitfun"], "default": is_default}
            models.append(current)
        elif current and stripped.startswith("Name:"):
            current["label"] = stripped.partition(":")[2].strip() or current["id"]
        elif current and stripped.startswith("Provider:"):
            current["provider"] = stripped.partition(":")[2].strip() or "bitfun"
    return models


def _bitfun_config_probe(bitfun_cli: str | None) -> dict[str, str]:
    if not bitfun_cli:
        return {"status": "unsupported", "issue": "BitFun CLI not found"}
    try:
        result = subprocess.run(
            [bitfun_cli, "models", "list"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "config_error", "issue": f"BitFun model probe failed: {exc}"}
    output = result.stdout + "\n" + result.stderr
    if "No AI models configured" in output:
        return {"status": "config_error", "issue": "No AI models configured in BitFun"}
    if result.returncode != 0:
        return {"status": "config_error", "issue": output.strip() or "BitFun model probe failed"}
    return {"status": "ready", "issue": "None"}


def _bitfun_debug() -> dict[str, Any]:
    project_root = Path.cwd()
    bitfun_source_cli = project_root / ".tools" / "BitFun" / "target" / "release" / "bitfun"
    bitfun_cli = os.environ.get("BITFUN_EXEC_BIN") or (str(bitfun_source_cli) if bitfun_source_cli.exists() else None) or shutil.which("bitfun")
    if not bitfun_cli:
        return {"status": "unsupported", "issue": "BitFun CLI not found"}
    model_probe = _bitfun_config_probe(bitfun_cli)
    result = subprocess.run(
        [bitfun_cli, "exec", "--auto", "--output-format", "json", "Reply exactly OK."],
        cwd="/private/tmp",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    output = result.stdout + "\n" + result.stderr
    status = "ok" if result.returncode == 0 else "error"
    if result.returncode != 0 and _looks_like_provider_auth_error(output):
        status = "auth_required"
    elif result.returncode != 0 and _looks_like_provider_config_error(output):
        status = "config_error"
    return {
        "status": status,
        "exit_code": result.returncode,
        "model_probe": model_probe,
        "command_shape": "bitfun exec --auto --output-format json 'Reply exactly OK.'",
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
        "issue": _bitfun_debug_issue(status, output),
    }


def _looks_like_provider_auth_error(output: str) -> bool:
    lowered = output.lower()
    return "401 unauthorized" in lowered or "authentication_error" in lowered or "authorized_error" in lowered


def _looks_like_provider_config_error(output: str) -> bool:
    lowered = output.lower()
    return "400 bad request" in lowered or "404 not found" in lowered or "model not found" in lowered or "invalid model" in lowered


def _bitfun_debug_issue(status: str, output: str) -> str:
    if status == "ok":
        return "BitFun CLI completed a minimal model call."
    if status == "auth_required":
        if "x-api-key" in output.lower():
            return "MiniMax rejected the request as missing/invalid X-Api-Key. The saved subscription key or endpoint account binding needs attention."
        return "MiniMax rejected the request as missing/invalid Authorization/API key."
    if status == "config_error":
        return "BitFun reached the provider, but the endpoint/model/protocol configuration is invalid."
    return "BitFun CLI failed before completing the minimal model call."


def _evaluation_conditions() -> dict[str, Any]:
    config = HarmonyConfig.from_env()
    contract = config.contract_snapshot()
    factory = _read_factory_summary()
    gui_config = _read_gui_config()
    return {
        "saved_config": gui_config,
        "prompt": {
            "policy": contract["prompt_policy"],
            "template": DEFAULT_PROMPT_TEMPLATE,
        },
        "environment": {
            **contract["environment"],
            "exported": config.command_env(),
        },
        "budget": {
            **contract["budget"],
            "timeout_sec": gui_config.get("timeout_sec"),
            "max_tokens": gui_config.get("max_tokens"),
        },
        "patch": {
            "policy": contract["patch_policy"],
            "workspace_policy": "Each harness runs in artifacts/<run-id>/<instance-id>/workspace copied from the case repository.",
            "scope_policy": "Benchmark scoring rejects edits outside the fixture files declared by the case.",
        },
        "evaluation": {
            "criteria": "oracle checks + unrelated edit detection + Harmony build validation when build metadata exists",
            "oracle": "Each case declares required snippets and forbidden snippets per file.",
            "build": {
                "enabled": bool(gui_config.get("run_build")),
                "target": gui_config.get("build_target") or "assembleHap",
                "timeout_sec": gui_config.get("build_timeout_sec") or 300,
                "skip_when": "The demo fixtures skip build validation when no Harmony build metadata is present.",
            },
        },
        "model_lock": {
            **contract["model_lock"],
            "required_model": gui_config.get("required_model"),
            "require_model_lock": gui_config.get("require_model_lock"),
            "selected_model": gui_config.get("selected_model"),
        },
        "cases": [
            {
                "instance_id": case.instance_id,
                "title": case.title,
                "instruction": case.instruction,
                "files": [file_spec.path for file_spec in case.files],
                "oracle": [
                    {
                        "path": rule.path,
                        "contains": rule.contains,
                        "not_contains": rule.not_contains,
                        "weight": rule.weight,
                    }
                    for rule in case.oracle
                ],
            }
            for case in CASES
        ],
        "benchmark_factory": {
            "modes": factory.get("factory_modes", {
                "Commit2Task": "Parent commit as base, target commit as reference.",
                "Test2Task": "Existing tests guide controlled defect injection.",
                "Build2Task": "Hvigor/ArkTS/module signals guide build repair tasks.",
                "UI2Task": "ArkUI pages and UI artifacts produce multi-layer UI oracles.",
            }),
            "task_package_schema": factory.get("task_package_schema", {}),
            "quality_gates": factory.get("quality_gates", []),
            "generated_tasks": factory.get("tasks", []),
            "output_root": factory.get("output_root"),
        },
    }


def _run_adapter(payload: dict[str, Any]) -> dict[str, Any]:
    required = ["instance_id", "run_id", "repo", "instruction", "harness_command"]
    missing = [key for key in required if not str(payload.get(key, "")).strip()]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    config = HarmonyConfig.from_env()
    config = HarmonyConfig(
        dev_eco_home=config.dev_eco_home,
        sdk_home=config.sdk_home,
        node_home=config.node_home,
        ohpm_bin=config.ohpm_bin,
        hvigor_bin=config.hvigor_bin,
        hdc_bin=config.hdc_bin,
        device_id=config.device_id,
        harness_command=str(payload["harness_command"]),
        timeout_sec=int(payload.get("timeout_sec") or config.timeout_sec),
        max_turns=int(payload["max_turns"]) if str(payload.get("max_turns") or "").strip() else config.max_turns,
        max_tokens=int(payload["max_tokens"]) if str(payload.get("max_tokens") or "").strip() else config.max_tokens,
        evaluation_criteria=str(payload.get("evaluation_criteria") or config.evaluation_criteria),
        model_name=str(payload.get("model") or config.model_name),
        actual_model=str(payload.get("model") or "") or config.actual_model,
        artifacts_root=Path(str(payload.get("artifacts_root") or config.artifacts_root)),
    )
    task = TaskSpec(
        instance_id=str(payload["instance_id"]),
        repo=Path(str(payload["repo"])),
        instruction=str(payload["instruction"]),
        base_commit=payload.get("base_commit"),
    )
    record = HarmonyAdapter(config).run_task(task, run_id=str(payload["run_id"]))
    artifact_dir = Path(str(record.metadata["artifact_dir"]))
    metadata = _read_text(artifact_dir / "metadata.json")
    contract = _read_text(artifact_dir / "contract.json")
    stdout = _read_text(artifact_dir / "agent_stdout.log")
    stderr = _read_text(artifact_dir / "agent_stderr.log")
    prompt = _read_text(artifact_dir / "prompt.txt")
    return {
        "instance_id": record.instance_id,
        "exit_code": record.metadata["exit_code"],
        "patch_bytes": len(record.model_patch.encode("utf-8")),
        "artifact_dir": str(artifact_dir),
        "patch": record.model_patch,
        "metadata": metadata,
        "contract": contract,
        "contract_json": json.loads(contract) if contract else {},
        "stdout": stdout,
        "stderr": stderr,
        "prompt": prompt,
    }


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _run_cmd(args: list[str], cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{args[0]} failed")


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), GuiHandler)
    url = f"http://{host}:{port}"
    print(f"HarmonyAdapter GUI running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping HarmonyAdapter GUI")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harmony-adapter-gui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
