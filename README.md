# job-search-agent

Pure-Python (stdlib only, no third-party dependencies) CLI toolkit for job hunting:

- **scout** — filter postings by freshness, level, location, and hard rules; dedupe
- **digest** — daily report: verified recommendations + pending-verification section
- **ats** — score a JD 0–100 with matched/missed skills
- **resume-check** — catch truthfulness violations before a resume goes out
- **submit** — human-in-the-loop form filling: the agent fills, you approve every submit click and every legal checkbox
- **track** — SQLite ledger of applications

## Make it yours (5 minutes)

The repo ships with neutral templates; your rules live only in the gitignored files.

```bash
cp config/preferences.example.yaml config/preferences.yaml
cp config/keywords.example.yaml config/keywords.yaml
cp config/user.example.yaml config/user.yaml   # then fill in your details
```

| Setting | File | What to fill in |
|---|---|---|
| Personal info (name, email, phone, address) | `config/user.yaml` (gitignored) | your contact details for application forms |
| Region & commute cities | `config/preferences.yaml` → `location` | `on_site_required_region`, `region_markers`, `reasonable_commute_cities` |
| Target keywords | `config/keywords.yaml` (gitignored) | your track keywords per track |
| Level rules | `config/preferences.yaml` → `levels` | accepted/excluded levels, year bands, `strong_match_ratio` |
| Freshness windows | `config/preferences.yaml` → `search` | `job_board_freshness_hours`, `university_freshness_days` |
| Staffing-agency blacklist | `config/preferences.yaml` → `filters` | `staffing_agency_blacklist` |

Without any personal config, the tool still runs on the neutral templates —
on-site postings pass with a `region_unconfigured` flag instead of being rejected.

## Architecture

```
                    +--------------------------+
                    | config/*.example.yaml    |  neutral templates (committed)
                    | config/preferences.yaml  |  your rules (GITIGNORED)
                    | config/keywords.yaml     |  your keywords (GITIGNORED)
                    | config/user.yaml         |  personal data (GITIGNORED)
                    +--------------------------+
                                 |
                                 v
  +----------------+   +--------------+   +-----------+   +------------+
  | scout.py       |   | digest.py    |   | ats.py    |   | preparer.py|
  | scan + filter  +-->| daily report +-->| JD score  +-->| resume     |
  | + dedupe       |   | verified only|   | 0-100     |   | truthfulness|
  +----------------+   +--------------+   +-----------+   +-----+------+
                                                                    |
                              +-------------------------------------+
                              |
                    +---------+---------+
                    | submitter.py      |  human-in-the-loop:
                    | fill -> gate      |  agent fills, human reviews,
                    | ReviewGate        |  legal items ALWAYS need
                    +-------------------+  explicit per-item consent
                              |
                    +---------+---------+
                    | tracker.py        |  SQLite ledger of applications
                    | QUEUED->...->     |  with a guarded status machine
                    | SUBMITTED         |
                    +-------------------+
```

### Modules

| Module | What it does |
|---|---|
| `jobagent/scout.py` | Filter postings: freshness windows, track classification, level judgement, location rules, staffing-agency / pre-sales / hard filters, dedupe |
| `jobagent/digest.py` | Daily digest: verified-only recommendation zone (configurable cap, per-track minimum, priority order) + separate pending-verification zone |
| `jobagent/ats.py` | Deterministic 0–100 JD scoring with matched/missed skills and apply/skip bands |
| `jobagent/preparer.py` | Resume truthfulness guards: configurable forbidden/required claims checked before a resume goes out |
| `jobagent/submitter.py` | Human-in-the-loop form filling: `FormFillPlan` (field provenance), `ReviewGate` (auto-submit only when all required fields are resolved and zero legal items are pending), `DryRunFiller` + `PlaywrightFiller` stub |
| `jobagent/tracker.py` | SQLite `applications` ledger with CRUD + guarded status transitions |
| `config/*.yaml`, `jobagent/config.py`, `jobagent/models.py` | All user-tunable rules, typed dataclasses, `Application` state machine |

## Quick start

```bash
# 1. create an isolated env (stdlib-only runtime; pytest needed for tests)
python3 -m venv .venv && .venv/bin/pip install -e . pytest

# 2. make it yours (see "Make it yours (5 minutes)" above)
cp config/preferences.example.yaml config/preferences.yaml
cp config/keywords.example.yaml config/keywords.yaml
cp config/user.example.yaml config/user.yaml   # fill in, or use JOBAGENT_* env vars

# 3. run the tests
.venv/bin/python -m pytest -q
```

## CLI usage

```bash
JA=.venv/bin/jobagent

# scout: filter a postings JSONL -> accepted JSONL
$JA scout postings.jsonl -o filtered.jsonl --seen seen.jsonl -v

# digest: accepted JSONL -> daily digest markdown
$JA digest filtered.jsonl --date 2026-10-07 -o digest.md

# ats: score a JD (JSON with jd_text/required/preferred/candidate_skills)
$JA ats jd.json

# resume-check: truthfulness guards over a resume text file (exit 1 on violation)
$JA resume-check resume.txt

# submit: dry-run demo of the fill -> review-gate state machine (touches no browser)
$JA submit --company Acme --title "Data Analyst"

# track: SQLite ledger
$JA track add --company Acme --title "Data Analyst" --url https://... --ats-score 82
$JA track list
$JA track status 1 FILLING
```

## PII warning

**Never commit real personal data to this repository.** The `.gitignore`
excludes `user.yaml`, `.env`, and `*.db`. Personal fields (name, email,
phone, address, LinkedIn, GitHub) are loaded ONLY from the gitignored
`config/user.yaml` or from `JOBAGENT_*` environment variables; the code
defaults to `<PLACEHOLDER>` values. `PlaywrightFiller` is intentionally a
stub: browser credentials are passed at runtime through a secure channel,
never stored in the repo.

## Publishing to GitHub

```bash
cd job-agent
git init
git add .
git status   # double-check: no user.yaml, no .env, no *.db, no real PII
git commit -m "Initial commit: job-search-agent v0.1.0"
# create the repo on github.com (public or private), then:
git remote add origin git@github.com:<you>/job-search-agent.git
git branch -M main
git push -u origin main
```

Before pushing, grep for leaks: `grep -riE "[0-9]{3}-[0-9]{3}-[0-9]{4}|@gmail|@ucdavis" --include="*.py" --include="*.yaml" --include="*.md" .`

---

## 中文摘要

纯 Python（仅标准库、零第三方依赖）的求职 CLI 工具包：

- **scout** —— 按新鲜度、级别、地点和硬规则过滤职位，去重
- **digest** —— 生成日报：只收已核实的推荐 + 单独的待核实区
- **ats** —— 给 JD 打 0–100 分，列出匹配 / 缺失技能
- **resume-check** —— 简历发出前先过真实性检查
- **submit** —— 人工审核的填表流程：agent 填表，每次提交点击和每个法律勾选框都由人确认
- **track** —— SQLite 申请记录

所有规则（时间窗、级别、地点、关键词、黑名单）都在配置文件里改，仓库自带中性模板，照"Make it yours"一节 5 分钟配好；个人信息只读 gitignored 的 `config/user.yaml` 或环境变量。六个子命令见上文 CLI 用法，`pytest` 全量测试。
