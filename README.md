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
                    | submitter.py      |  Hermes-style human-in-the-loop:
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

### Module map (old markdown agents -> code)

| Old agent / doc              | Code module              | Responsibility |
|------------------------------|--------------------------|----------------|
| 猎手 scout (`scout_brief.md`) | `jobagent/scout.py`      | freshness windows (24h job boards / 14d university), track classification, level judgement, location, staffing-agency + pre-sales + hard filters, dedupe |
| scout daily report           | `jobagent/digest.py`     | verified-only recommendation zone (cap 20, per-track minimum 3, Primary > Secondary > Extended > Selective), separate pending-verification zone |
| 投递手 preparer (`preparer_brief.md`) ATS step | `jobagent/ats.py` | deterministic 0-100 JD scoring with matched/missed lists and bands (priority >= 85, recommend 75-84, low 60-74, skip < 60) |
| 投递手 preparer authenticity  | `jobagent/preparer.py`   | resume truthfulness guards (Weibo title, sponsorship phrase, work-auth header, SAS qualifier, no GPA, graduation date) |
| submitter (Hermes-style)     | `jobagent/submitter.py`  | `FormFillPlan` (field provenance: user_config / simplify / needs_user), `ReviewGate.can_auto_submit` (all required fields resolved AND zero pending legal items), `DryRunFiller` + `PlaywrightFiller` stub |
| Excel tracker                | `jobagent/tracker.py`    | SQLite `applications` table with CRUD + guarded status transitions |
| preferences / experience docs | `config/*.yaml`, `jobagent/config.py`, `jobagent/models.py` | rule configuration, typed dataclasses, `Application` state machine |

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

这是一个把原来写在 markdown 文档里的求职 pipeline 规则（猎手 scout / 投递手 preparer / 投递 submitter / 跟踪 tracker）转成**可测试、可版本化的 Python 代码**的项目，风格对标 Hermes：**机械填表由 agent 做，最终提交点击和每一个法律勾选框永远归人**。

- **零第三方依赖**：只用 Python 标准库，到处都能跑；测试需要 `pytest`。
- **核心规则都已编码**：24h/14d 新鲜度窗口、四档 track 分类、级别判断（含 0–2 年 new-grad-only 的 overqualified 警告旗）、湾区通勤地点规则、中介/售前/硬过滤、去重；日报只收 JD 已核实职位（20 条上限、每 track 至少 3 条）；ATS 0–100 确定性打分；简历真实性六条红线检查；提交前的 ReviewGate（必填项齐全 + 无未决法律项才允许自动提交，法律项永远逐项人工同意）。
- **隐私安全**：个人信息只从 gitignored 的 `config/user.yaml` 或环境变量读取，仓库里只有占位符；浏览器凭证永不进仓库。
- **使用**：`jobagent scout/digest/ats/resume-check/submit/track` 六个子命令，详见上文；`pytest` 全量测试。
