# Demo script — Investment Committee: "Should we buy COIN?" (live)

**The room:** a public-markets fund's IC, revisiting Coinbase. **Sarah Kim** (Portfolio
Manager, decides, skeptic) and **Alex Rivera** (Equity Analyst, did the digging). The
**agent ("tellmequick")** listens in the background and interjects when a strong, fresh match
turns up across the three Moss indexes — `knowledge` (Coinbase filings), `slack` (the team's
debate), `meetings` (the prior IC decision). It also answers when addressed by name.

Every beat lists the **question**, the **indexes it pulls**, and the **verified fact**. The
power move is one question lighting up *a filing + a teammate's Slack line + the prior decision*.

---

**B0 — Sarah:** "Alright, Coinbase. We're revisiting — let's decide buy or no-buy today."

### Beat 1 — "Didn't we already pass on this?" → meetings + slack
**Sarah:** "Remind me where we landed last time, I don't want to relitigate."
**🤖** "On May 15 the IC **passed for now** — revisit after the print and restructuring clarity, owner Sarah; the concern was revenue concentration in volatile transaction fees. The risk note said any entry is a **starter, ≤1% of NAV**, pending S&S diversification. — prior IC decision + #risk"
- *Pulls:* `meetings` (May-15 decision + risk note) + `slack` (#risk sizing rule).

### Beat 2 — "What changed — the layoffs?" → slack + knowledge (8-K)
**Sarah:** "What's actually different now? Alex flagged a restructuring."
**Alex:** "Right, I posted about it but don't have the exact figure in front of me."
**🤖** "Coinbase cut **~700 roles, ~14% of staff**, with a **$50–60M** charge, framed as optimizing for the AI era. Alex's read in #coin-research was 'discipline, not distress.' — 8-K (May 2026) + #coin-research"
- *Pulls:* `knowledge` (8-K layoffs) + `slack` (Alex's take).

### Beat 3 — "Are insiders bailing?" → slack + knowledge (Form 4)
**Sarah:** "A 14% cut — are the execs themselves heading for the exits?"
**🤖** "No. The CFO's ~$2M sale was a **pre-set 10b5-1 plan**, and the COO's Form 4 'sale' was just **tax withholding on a performance-RSU vest** — she netted ~340K shares. — Form 4 filings + #coin-research"
- *Pulls:* `knowledge` (Form 4) + `slack`.

### Beat 4 — "Who else holds it?" → knowledge (SC 13G)
**Alex:** "And the holder base is real money."
**Sarah:** "Give me the numbers."
**🤖** "Vanguard **7.37%**, BlackRock **5.7%**, Jane Street **5.3%**, ARK **5.14%** — roughly a quarter of the float in the top four. (Note: Jane Street is market-making, not a long-term holder.) — Schedule 13G filings"
- *Pulls:* `knowledge` (SC 13G) + the `slack` caveat Sarah raised.

### Beat 5 — "Still just trading-fee revenue?" → knowledge (10-K) + slack
**Sarah:** "My whole hesitation is they're a one-trick trading shop. Is that still true?"
**🤖** "Less so. FY2025 total revenue **$7.18B**, up from **$6.56B**; subscription & services keeps growing as a share — that's the diversification the team's been tracking. Transaction revenue is still the cyclical swing factor. — FY2025 10-K MD&A + #coin-research"
- *Pulls:* `knowledge` (10-K revenue) + `slack`.

### Beat 6 — "What's the biggest risk?" → knowledge (10-K risk) + slack (#risk)
**Sarah:** "And the bear case, in their own words?"
**🤖** "Their 10-K names dependence on **crypto trading volume and market conditions** as the top revenue risk — a sustained downturn would materially cut revenue. Your #risk thread called this 'the thing that makes us wrong.' — FY2025 10-K Risk Factors + #risk"
- *Pulls:* `knowledge` (10-K risk factors) + `slack` (#risk).

### Beat 7 — "Is management aligned?" → knowledge (DEF 14A)
**Sarah:** "tellmequick, how is the CEO paid?"  *(addressed → always answers)*
**🤖** "Brian Armstrong's base salary is ~$350,000; the bulk of his pay is multi-year equity that vests on performance. He's Chairman and CEO, with Marc Andreessen on the board. Pay is mostly at-risk. — DEF 14A proxy"
- *Pulls:* `knowledge` (DEF 14A).

### Beat 8 — Empty state (honesty) → nothing
**Sarah:** "What's their actual AI product roadmap — what are they shipping?"
**🤖** *(stays silent — no high-confidence match)*
**Alex:** "That's the open item from #ic-prep — the filings only say 'AI era,' no product detail. We treat it as unknown." → agent didn't bluff.

---

**B9 — Sarah:** "OK. We passed for diversification evidence and no insider exodus — we now have both, smart money's in, and the restructuring reads as discipline. **Initiate a starter, 1% of NAV**, revisit after next quarter's S&S print."

## Judge-appeal cheat sheet
- **Cross-index (the differentiator):** Beats 1, 2, 3, 5, 6 each fuse `knowledge` + `slack` (+ `meetings`) in one answer.
- **Memory / "didn't we decide?":** Beat 1 pulls the prior IC decision verbatim.
- **Unstructured parsing (Unsiloed):** the numbers in Beats 2–7 come from parsed 8-K / Form 4 / SC 13G / 10-K / proxy.
- **Honesty:** Beat 8 refuses to answer what the filings don't contain.
- **LiveKit:** interjections ride the natural Sarah/Alex back-and-forth; Beat 7 shows explicit address.
