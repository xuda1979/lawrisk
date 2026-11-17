"""Deterministic, keyword/rule-based risk scoring engine.

Design rules ("低算力守则"): everything is compiled regex over the already
extracted paragraphs + extracted fields. No randomness, no external calls, so
identical input always yields the identical score (AC1). Every penalty carries a
human-readable reason and a verbatim source excerpt (AC2).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import List

from lawrisk.models import (
    Dimension,
    DimensionScore,
    Penalty,
    RiskLevel,
    RiskReport,
)
from lawrisk.textutil import looks_like_heading

ENGINE_VERSION = "lawrisk-engine-v1"

# Maximum number of exemplars kept per rule so long docs stay readable.
MAX_CITES_PER_RULE = 3

# Weights used to aggregate dimension scores into the 0-100 overall score.
DIM_WEIGHTS = {
    Dimension.COMMERCIAL: 0.35,
    Dimension.LIABILITY: 0.30,
    Dimension.DATA: 0.20,
    Dimension.EXPORT: 0.15,
}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    dimension: Dimension
    pattern: re.Pattern[str]
    severity: int
    reason: str
    condition: re.Pattern[str] | None = None
    exclusion: re.Pattern[str] | None = None
    description: str = ""
    mitigation: str = ""


_CARVEOUT = re.compile(
    r"(?:unless|except|provided that|provided it gives|if[^.]{0,25}(?:notice|consent|object))",
    re.IGNORECASE,
)
_MUTUAL = re.compile(r"(?:either|each|both|any)\s+(?:party|parties)", re.IGNORECASE)

RULES: List[Rule] = [
    # ---------------------------------------------------------------- commercial
    Rule(
        rule_id="R-COMM-1",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"auto[- ]?renew(?:s|al)?|automatic renewal(?:s)?|"
            r"renew(?:s|ed|ing)? automatically|automatically renew(?:s|ed|ing)?|"
            r"renew(?:s|ed|ing)?[^.;]{0,40}automatically|"
            r"(?:is|shall|will|may) be (?:extended|renewed)[^.;]{0,40}automatically|"
            r"(?:be )?deemed (?:to be )?(?:extended|renewed)[^.;]{0,40}automatically|"
            r"(?:be )?deemed (?:to be )?automatically (?:extended|renewed)[^.;]{0,15}|"
            r"(?:is|shall|will|may) automatically (?:be )?(?:extended|renewed)[^.;]{0,15}|"
            r"automatically extend(?:s|ed|ing)?|automatic(?:al)? extension(?:s)?|"
            r"(?:shall|will|may) continue (?:in effect|in force|for)[^.;]{0,40}"
            r"(?:successive|from term to term|renewal (?:terms?|periods?)|"
            r"additional (?:successive )?(?:terms?|periods?))",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:no auto[- ]?renewal|without auto[- ]?renewal|"
            r"(?:no|without) automatic renewal|"
            r"(?:does|shall|will|may) not (?:be )?(?:auto[- ]?renew|"
            r"renew(?:s|ed|ing)? automatically|automatically renew(?:s|ed|ing)?)|"
            r"(?:does|shall|will|may) not (?:be )?renewed automatically|"
            r"(?:is|shall|will|may) not (?:be )?deemed (?:to be )?(?:extended|renewed) automatically|"
            r"(?:shall|will|may) (?:be )?deemed (?:to be )?not (?:extended|renewed)|"
            r"(?:is|shall|will|may) be (?:extended|renewed)[^.;]{0,40}automatically"
            r"[^.;]{0,80}(?:notice of non[- ]renewal|notice[^.;]{0,35}not to renew)|"
            r"(?:is|shall|will|may) be automatically (?:extended|renewed)"
            r"[^.;]{0,80}(?:notice of non[- ]renewal|notice[^.;]{0,35}not to renew)|"
            r"shall be deemed not renewed|"
            r"(?:neither party|no party)[^.;]{0,60}"
            r"(?:auto[- ]?renew|renew(?:s|ed|ing)? automatically|automatically renew(?:s|ed|ing)?)|"
            r"(?:either party|neither party|no party)[^.;]{0,80}"
            r"(?:elect(?:s|ing)?|choos(?:es|e|ing)?|opt(?:s|ing)?|intend(?:s|ing)?) not to renew|"
            r"(?:auto[- ]?renew|renew(?:s|ed|ing)? automatically|automatically renew(?:s|ed|ing)?|automatic renewal)"
            r"[^.;]{0,80}(?:notice of non[- ]renewal|notice[^.;]{0,35}not to renew)|"
            r"(?:is|shall|will|may) automatically (?:be )?(?:extended|renewed)"
            r"[^.;]{0,80}(?:notice of non[- ]renewal|notice[^.;]{0,35}not to renew|"
            r"object(?:s|ing)? in writing|written objection|"
            r"written notice of (?:termination|cancellation)[^.;]{0,40}"
            r"(?:prior to|before)[^.;]{0,25}(?:expiration|expiry))|"
            r"(?:either party|neither party)[^.;]{0,80}object(?:s|ing)? in writing|"
            r"(?:either party|neither party)[^.;]{0,80}written objection|"
            r"\b(?:either party|neither party)[^.;]{0,80}"
            r"(?:may|shall|will)?\s*(?:give(?:s|n)?|deliver(?:s|ed)?|provide(?:s|d)?)"
            r"\b[^.;]{0,40}written notice of (?:termination|cancellation)[^.;]{0,40}"
            r"(?:prior to|before)[^.;]{0,25}(?:expiration|expiry)|"
            r"(?:automatically\s+renew|auto[- ]?renew(?:s|al)?|automatic renewal)"
            r"[^.;]{0,60}(?:unless|except|provided\s+(?:that|it))[^.;]{0,60}"
            r"(?:terminated?(?: in writing)?|notices? in writing|written notice)"
            r"(?: by either party)?|"
            r"(?:deemed|continue (?:in effect|in force|for))[^.;]{0,80}"
            r"(?:notice of non[- ]renewal|notice[^.;]{0,35}not to renew|"
            r"object(?:s|ing)? in writing|written objection|"
            r"written notice of (?:termination|cancellation)[^.;]{0,40}"
            r"(?:prior to|before)[^.;]{0,25}(?:expiration|expiry)))",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Automatic renewal without an explicit opt-out window",
        mitigation="Require explicit written opt-in for renewal, add a >60 day renewal notice window, or remove auto-renewal.",
        description="Detects automatic-renewal terms that roll the contract forward with no opt-out window.",
    ),
    Rule(
        rule_id="R-COMM-2",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"\b(?:terminat(?:e|es|ed|ing|ion)|end(?:s|ed|ing)?|cancel(?:s|led|ling)?|terminab(?:le|ility))\b[^.]{0,40}"
            r"(?:without cause|for any(?: reason| purpose)?|for no reason|at will|"
            r"(?:at|for)\s+(?:its|our|their|the (?:provider|company|vendor))? ?(?:own |sole |absolute )?convenience|"
            r"for convenience|without assigning any reason|without (?:any )?reason\b)"
            r"|(?:at|for)\s+(?:its|our|their|the (?:provider|company|vendor))? ?(?:own |sole |absolute )?convenience"
            r"[^.;]{0,45}\b(?:terminat(?:e|es|ed|ing|ion)|end(?:s|ed|ing)?|cancel(?:s|led|ling)?)\b",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:{})|(?:{})|"
            r"(?:where|as|if|to the extent)\s+(?:so\s+)?required\s+by\s+(?:applicable\s+)?law\b|"
            r"(?:by\s+order\s+of\s+(?:a\s+)?court|(?:by|under|pursuant\s+to)\s+(?:applicable\s+)?law\b|court\s+order\b)".format(_CARVEOUT.pattern, _MUTUAL.pattern),
            re.IGNORECASE,
        ),
        severity=25,
        reason="One-sided termination-without-cause right for the counterparty",
        mitigation="Make termination rights mutual — require cause, mutual consent, or equal notice/fee windows for both parties.",
        description="Detects a one-sided right to terminate without cause or for convenience.",
    ),
    Rule(
        rule_id="R-COMM-3",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"(?:reserves the right to (?:adjust|increase|change|modify|revise|update)|"
            r"(?:shall|will|may)\s+have the (?:right|option) to (?:adjust|increase|change|modify|revise|update)|"
            r"may (?:adjust|increase|change|modify|revise|update)|(?:can|may) adjust|(?:can|may) revise|"
            r"(?:can|may|shall|will) update)"
            r" (?:the )?(?:(?:monthly|annual|yearly|service|platform|subscription|"
            r"license|licence|usage)\s+)?(?:price|prices|fees|fee|pricing)"
            r"|(?:price|prices|fees|fee)[^.;]{0,30}(?:may|shall|will|can) be "
            r"(?:adjusted|increased|changed|modified|revised|altered)"
            r"|(?:prices?|fees?)\s+(?:may|shall|will|can)\s+(?:change\b|increase\b|rise\b|escalate\b)|"
            r"(?:prices?|fees?)\s+(?:are|is|shall be|will be|may be)\s+subject to\s+change\b|"
            r"price (?:increase|escalation)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:no price increase|without (?:any )?price increase|"
            r"there (?:shall|will|can|is|be) no|"
            r"by mutual(?: written)? agreement|mutual written consent|"
            r"(?:in accordance with|in line with|per the|as per) [^.;]{0,40}"
            r"(?:consumer price index|cpi|index(?:ed)?))",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Unilateral price adjustment clause without consent requirement",
        mitigation="Cap annual fee increases at a fixed percentage with 60+ days written notice, or require mutual written consent.",
        description="Detects unilateral fee or price increases without agreed consent mechanics.",
    ),
    Rule(
        rule_id="R-COMM-4",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(r"assign\s*:\s*|assign(?: (?:this agreement|all (?:of )?its? rights?(?: and obligations)?(?: and interests?)?|its? rights? and obligations under (?:this agreement|the agreement)|its? interests? (?:under|in) (?:this agreement|the agreement)))?[^.]{0,40}(?:without[^.]{0,30}consent|to any third party)|transfer(?: (?:all|any) (?:of )?its? rights?(?: and obligations)?(?: under (?:this |the )?agreement|in(?:to| under) this agreement)?)?[^.]{0,40}(?:without[^.]{0,30}consent|to any third party)|transfer this agreement[^.]{0,30}without|(?:may|can)\s+assign this agreement\s+at any time|this agreement (?:may|shall) be assigned (?:to any third party )?(?:by [^.;]{0,30})?without|novat(?:e|es|ed|ing)?\s+(?:this agreement|the agreement)?[^.]{0,40}(?:without[^.]{0,30}consent|to any third party)", re.IGNORECASE),
        exclusion=re.compile(
            r"(?:(?:neither|either|each|both) party (?:may|shall|will)(?: not)? assign|"
            r"(?:may|shall|will) not assign(?: this agreement)?|"
            r"assign[^.]{0,60}(?:to an affiliate|(?:with|upon|under|subject to) (?:the )?(?:prior )?written consent))",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Assignment without the other party's prior written consent",
        mitigation="Add mutual prior-written-consent approval for any assignment, and carve out assignment to an affiliate.",
        description="Detects assignment of the agreement without the other party's prior consent.",
    ),
    Rule(
        rule_id="R-COMM-5",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"(?:"
            r"(?:may|can|reserves? the right to|is (?:entitled|authorised|authorized) to)"
            r"[^.]{0,30}"
            r"(?:amend|modify|alter|vary|change|revise|update)\s+"
            r"(?:this agreement|these presents|these terms|the terms|the terms and conditions|"
            r"any (?:of the )?(?:term|provision|clause|condition)s?[^.]{0,8}hereof)"
            r"[^.]{0,35}"
            r"(?:at any time|at (?:its|his|their)? ?(?:own )?(?:sole|absolute) discretion|"
            r"without (?:prior )?(?:notice|consent|approval)|unilaterally|from time to time)"
            r")|"
            r"(?:may|can|reserves? the right to|is (?:entitled|authorised|authorized) to)"
            r"[^.]{0,20}(?:amend|modify|alter|vary|change|revise|update)\s+"
            r"(?:this agreement|these presents|these terms|the terms|the terms and conditions|"
            r"any (?:of the )?(?:term|provision|clause|condition)s?[^.]{0,8}hereof|"
            r"such (?:terms|conditions))"
            r"[^.]{0,15}(?:at (?:its|his|their)? ?(?:own )?(?:sole|absolute) discretion)|"
            r"(?:these terms|the terms and conditions|the terms|this agreement)"
            r"[^.]{0,35}(?:may|can|shall|will) be (?:amended|modified|altered|varied|changed|revised|updated)"
            r"[^.]{0,25}(?:by(?: the)? (?:provider|company|vendor|licensor|supplier))"
            r"[^.]{0,40}(?:at any time|without (?:prior )?(?:notice|consent|approval)|"
            r"at (?:its|their|the (?:provider|company|vendor))? ?(?:own )?(?:sole|absolute) discretion|"
            r"unilaterally|from time to time)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:{}|"
            r"by mutual (?:written )?(?:agreement|consent)|"
            r"mutual written consent|"
            r"with (?:the )?(?:prior )?written consent of (?:both|either|each) parties?)".format(
                _MUTUAL.pattern
            ),
            re.IGNORECASE,
        ),
        severity=20,
        reason="Unilateral amendment of the agreement or its terms without mutual written consent",
        mitigation="Require amendments to be agreed in writing by both parties; allow only limited, notice-based administrative changes.",
        description="Detects unilateral amendment of the agreement or its terms without mutual consent.",
    ),
    Rule(
        rule_id="R-COMM-6",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"(?:late payment(?:s)?|overdue (?:amounts?|invoices?)|delinquent accounts?|"
            r"late fee(?:s)?|late charge(?:s)?|penalty charge(?:s)?|delinquency (?:fee|charge)|"
            r"overdue (?:fee|charge))"
            r"[^.;]{0,40}(?:interest|penalty|fee|charge)|"
            r"(?:late fee(?:s)?|late charge(?:s)?|penalty charge(?:s)?|delinquency (?:fee|charge)|"
            r"overdue (?:fee|charge)|finance charge(?:s)?)"
            r"[^.;]{0,20}(?:at|of|=)[^.;:]{0,12}"
            r"(?:a rate of\s*)?\d+(?:\.\d+)?\s*%(?:[^.;]{0,12}per (?:month|annum|year))?|"
            r"(?:interest|penalty|service charge|finance charge|carrying charge)[^.;]{0,45}(?:on|for)"
            r"[^.;]{0,20}(?:overdue|delinquent|late|unpaid)[^.;]{0,20}(?:at|of|=)[^.;:]{0,12}"
            r"(?:a rate of\s*)?\d+(?:\.\d+)?\s*%|"
            r"(?:interest|penalty|fee|charge)[^.;]{0,20}(?:at|of|=)[^.;:]{0,30}"
            r"(?:a rate of\s*)?\(?\d+(?:\.\d+)?\)?\s*%(?:[^.;]{0,12}per (?:month|annum|year))?"
            r"[^.;]{0,40}(?:on|for)[^.;]{0,20}(?:overdue|delinquent|late|unpaid)|"
            r"(?:late fee(?:s)?|late charge(?:s)?|penalty charge(?:s)?|delinquency (?:fee|charge)|"
            r"overdue (?:fee|charge)|finance charge(?:s)?|carrying charge(?:s)?|service charge(?:s)?)"
            r"[^.;]{0,20}(?:of|=|at|:)\s*\$[0-9][0-9,]*(?:\.\d+)?[^.;]{0,25}"
            r"(?:per |for each |for every |each |weekly |daily |monthly |annually|accrues|accruing|accrual)|"
            r"(?:late fee(?:s)?|late charge(?:s)?|penalty charge(?:s)?|delinquency (?:fee|charge)|"
            r"overdue (?:fee|charge)|finance charge(?:s)?|carrying charge(?:s)?|service charge(?:s)?)"
            r"[^.;]{0,20}(?:of|=|at|:)[^.;:]{0,10}\d+(?:\.\d+)?\s*%|"
            r"(?:unpaid|past[ -]?due|delinquent|overdue)\s+(?:invoices?|balances?|amounts?|payments?|fees?|accounts?)"
            r"[^.;]{0,30}(?:accrue(?:s|d|ing)?|bear(?:s|ing)?|shall|will|may)"
            r"[^.;]{0,20}(?:interest|penalty|finance[ -]?charge|service[ -]?charge|"
            r"carrying charge|late (?:fee|charge))"
            r"[^.;]{0,10}(?:at|of|=)[^.;:]{0,12}(?:a rate of\s*)?\d+(?:\.\d+)?\s*%|"
            r"(?:invoices?|balances?|amounts?|payments?|fees?|accounts?)"
            r"[^.;]{0,35}past[ -]?due[^.;]{0,25}(?:accrue(?:s|d|ing)?|bear(?:s|ing)?|shall|will|may)"
            r"[^.;]{0,20}(?:interest|penalty|finance[ -]?charge|service[ -]?charge|"
            r"carrying charge|late (?:fee|charge))"
            r"[^.;]{0,10}(?:at|of|=)[^.;:]{0,12}(?:a rate of\s*)?\d+(?:\.\d+)?\s*%",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:statutory|legal|applicable)[^.;:,]{0,20}(?:rate|interest|maximum|ceiling|cap|limit)|"
            r"market rate|prevailing (?:market )?rate|prime rate|"
            r"(?:ecb\s+rate|base rate|reference rate|benchmark rate|central[- ]bank rate)|"
            r"euribor|libor|sofr\b|sonia\b|"
            r"late payment (?:act|legislation|directive|regulations?)|"
            r"in accordance with (?:applicable )?law|as (?:required|per) (?:statute|law)|"
            r"required by (?:statute|law|applicable law)",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Late-payment interest/penalty applies to the counterparty above market rates",
        mitigation="Cap late-payment interest at a statutory or market rate and add a grace period before interest accrues.",
        description="Detects above-market late-payment interest, penalties, fees or service charges.",
    ),
    Rule(
        rule_id="R-COMM-7",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"non[ -]?refundable(?: and non[ -]?cancellable)?|non[ -]?cancellable|"
            r"non[ -]?returnable(?: and non[ -]?creditable)?|non[ -]?creditable|"
            r"no (?:credits?,?\s*(?:returns?,?\s*)?(?:or\s+)?)?refunds?\s+"
            r"(?:shall|will|may|can|cannot?|may not)\s+(?:be\s+)?(?:made|given|paid|issued)|"
            r"refunds? (?:will|shall) not (?:be )?(?:made|given|paid|issued)|"
            r"(?:payments?|fees?)[^.;]{0,35}(?:are|shall be|will be)? final[^.;]{0,40}"
            r"(?:shall|will) not (?:be )?refunded",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:" + _CARVEOUT.pattern + r")|"
            r"unless[^.;]{0,60}(?:defect|defective|quality|warrant)|"
            r"(?:defect|defective|quality issue)[^.;]{0,40}refund|"
            r"refunds?[^.;]{0,40}(?:defect|defective|quality)",
            re.IGNORECASE,
        ),
        severity=15,
        reason="Fees are non-refundable / non-cancellable, locking the counterparty into payment",
        mitigation="Allow pro-rata refunds or termination credits for unused services and carve out cancellation-for-cause.",
        description="Detects all-fees non-refundable or non-cancellable terms that lock in payment.",
    ),
    Rule(
        rule_id="R-COMM-8",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"(?:suspend|deactivate)[^.]{0,60}"
            r"(?:the services|services|access|the account|any account)"
            r"[^.]{0,50}"
            r"(?:without (?:prior )?(?:notice|consent|warning)|"
            r"at any time|"
            r"at (?:its|our|provider'?s)[^.]{0,15}(?:sole|absolute)[^.]{0,15}(?:discretion)|"
            r"with immediate effect)"
            r"|"
            r"(?:without (?:prior )?(?:notice|consent|warning)|at any time|"
            r"at (?:its|our|provider'?s)[^.]{0,15}(?:sole|absolute)[^.]{0,15}(?:discretion)|"
            r"with immediate effect)"
            r"[^.]{0,50}(?:suspend|deactivate)[^.]{0,60}"
            r"(?:the services|services|access|the account|any account)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:{})|(?:{})|"
            r"(?:where|as|if|to the extent)\s+(?:so\s+)?required\s+by\s+(?:applicable\s+)?law\b|"
            r"(?:by\s+order\s+of\s+(?:a\s+)?court|(?:by|under|pursuant\s+to)\s+(?:applicable\s+)?law\b|court\s+order\b)".format(_CARVEOUT.pattern, _MUTUAL.pattern),
            re.IGNORECASE,
        ),
        severity=20,
        reason="Unilateral suspension of services/account by the counterparty without notice or consent",
        mitigation="Require notice, a cure period and cause for any suspension, and credit for service downtime.",
        description="Detects unilateral suspension of the services or account without notice or consent.",
    ),
    # ----------------------------------------------------------------- liability
    Rule(
        rule_id="R-LIAB-1",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(r"((?:in no event|under no circumstances)) (?:shall|will) (?:the )?(?:provider|company|vendor|supplier|licensor)|(?:provider|company|vendor|supplier|licensor) (?:shall|will) (?:not (?:be )?(?:liable|responsible|held liable)(?:\s+(?:or|and)\s+(?:liable|responsible))?|not have (?:any|no) liability|have no liability) for", re.IGNORECASE),
        exclusion=re.compile(r"(?:fraud|death|personal injury|gross negligence|wilful misconduct|willful misconduct|neither party|both parties|each party|either party)", re.IGNORECASE),
        severity=25,
        reason="Broad disclaimer covering consequential/indirect damages",
        mitigation="Carve out fraud, death or personal injury, gross negligence and willful misconduct from the exclusion.",
        description="Flags broad consequential or indirect liability disclaimers with no carve-outs present.",
    ),
    Rule(
        rule_id="R-LIAB-2",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(
            r"(?:(?:total |aggregate |maximum )?liability[^.]{0,60}"
            r"(?:limited to|shall not exceed|shall (?:in no event|never) exceed|in excess of|capped? at)|"
            r"(?:in no event|under no circumstances|in any event)?\s*(?:shall|will)?\s*"
            r"(?:the )?(?:total |aggregate |maximum )?liability[^.;]{0,50}"
            r"exceed(?:s|ing)?\b)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:shall|will|is|is hereby|be) not (?:be )?limited(?: to)?|"
            r"not be limited to|not limited to|"
            r"liability[^.;]{0,40}shall not (?:be )?limited|"
            r"no (?:limitation|cap) (?:of|on) liability|"
            r"nothing in (?:this|any) (?:clause|section|agreement)[^.;]{0,40}(?:limits?|caps?|excludes?)|"
            r"without limitation of liability|"
            r"not subject to any (?:limitation|cap)|"
            r"(?:(?:total |aggregate )?liability[^.;]{0,30}(?:of|for) "
            r"(?:each party|either party|both parties)"
            r"|(?:each party|either party|both parties)'?s?[^.;]{0,30}(?:total |aggregate |maximum )?liability)"
            r"[^.;]{0,120}"
            r"(?:paid (?:or|and) received|received (?:or|and) paid|"
            r"(?:paid|received)\s+(?:by|from)\s+(?:the )?(?:other|either|each|any|such) party|"
            r"amounts? actually paid)",
            re.IGNORECASE,
        ),
        severity=25,
        reason="Aggregate liability cap may be below expected exposure",
        mitigation="Negotiate a cap that covers realistically foreseeable loss; base it on fees for 12 months or more.",
        description="Flags an aggregate liability cap that may sit below expected exposure.",
    ),
    Rule(
        rule_id="R-LIAB-3",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(
            r"(?:indemnif(?:y|ies)[^.]{0,60}(?:against|from)[^.]{0,60}"
            r"(?:all|any|third[ -]party|losses|damages|claims)|"
            r"(?:held|hold(?:s|ing)?)[^.]{0,25}harmless)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:each party indemnif|either party indemnif|"
            r"each party hold|either party hold|"
            r"each party[^.;]{0,25}(?:hold|held)|"
            r"mutual(?:ly)? indemnif|"
            r"arising (?:out of|from) (?:its own|the indemnifying party's own|"
            r"such party's own) (?:breach|negligence)|"
            r"to the extent (?:caused by|arising from) (?:its |the indemnifying party's )?own|"
            r"(?:each|either|both) party[^.;]{0,40}for its own (?:breach|negligence))",
            re.IGNORECASE,
        ),
        severity=30,
        reason="Broad indemnification obligation in favour of the counterparty",
        mitigation="Limit indemnity to third-party IP- or breach-specific claims and add mutual caps and carve-outs.",
        description="Flags a broad indemnification obligation in favour of the counterparty.",
    ),
    Rule(
        rule_id="R-LIAB-4",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(
            r"(?:as[ -]is|without (?:any )?warrant(?:y|ies)|"
            r"(?:makes?|gives?|offers?)\s+no\s+(?:warrant(?:y|ies)|representation(?:s)?)\b|"
            r"no\s+(?:warrant(?:y|ies)?|representation(?:s)?)\s+of\s+any\s+kind\b|"
            r"disclaim(?:s|ing|ed)?[^.]{0,25}(?:all (?:warrant(?:y|ies)|(?:warrant(?:y|ies) and (?:representations?|conditions?)))|"
            r"warrant(?:y|ies),?\s+express or implied)\b)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:warrant(?:y|ies)[^.;]{0,40}(?:set forth|in this (?:agreement|clause|section)|"
            r"(?:shall|will) apply|remain)|"
            r"(?:notwithstanding|except as (?:set forth|provided)|provided\s+that\b|however|but)\b"
            r"[^.;]{0,80}warrant|"
            r"(?:each|either|both|neither) party[^.;]{0,50}(?:makes?|gives?|offers?)?\s*"
            r"no\s+(?:warrant(?:y|ies)|representation(?:s)?)\b)",
            re.IGNORECASE,
        ),
        severity=30,
        reason='"As-is" delivery with warranties disclaimed',
        mitigation="Restore basic warranties (conformity, availability) and remove absolute as-is disclaimers.",
        description='Flags "as-is" delivery of the services with warranties disclaimed.',
    ),
    Rule(
        rule_id="R-LIAB-5",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(
            r"(?:does not|will not|shall not|makes? no|disclaim(?:s|ing|ed)?)[^.]{0,40}"
            r"(?:warrant(?:y|ies?)?|guarantee|represent)[^.]{0,40}"
            r"(?:uninterrupted|error[- ]?free|available|availability|reliab|"
            r"fit for|fitness for|merchantab|suitab|"
            r"meet(?:s|ing)?[^.]{0,25}(?:requirements?|expectations?|specifications?)|"
            r"particular purpose)|"
            r"(?:availability|reliab\w*|error[- ]?free (?:operation|performance)|"
            r"uninterrupted (?:operation|performance|service))[^.;]{0,45}"
            r"(?:is|are|shall be|will be|can be|may be)\s+not\s+guaranteed",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Availability / quality of services is disclaimed (interruption or error-free operation not warranted)",
        mitigation="Add service-level and availability commitments with remedies for sustained downtime.",
        description="Flags disclaimers of service availability or error-free, uninterrupted operation.",
    ),
    Rule(
        rule_id="R-LIAB-6",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(
            r"liquidated damages[^.]{0,80}(?:forfeit|penalty|per[ -]?(?:day|week|month|occurrence|event)|"
            r"fixed (?:amount|sum))|"
            r"liquidated damages\b|"
            r"(?:penalt(?:y|ies)|fixed charge(?:s)?|forfeit(?:ure)?)[^.;]{0,60}"
            r"(?:\$[^.;]{0,20}(?:per |for each |for every |upon)|"
            r"forfeit(?:ed|ing)?\b|per[ -]?(?:day|week|month|occurrence|event)\b|"
            r"(?:\d+(?:\.\d+)?\s*%|\$\s?\d[\d,.]*|\d[\d,.]*\s*(?:USD|EUR|GBP|AUD|CAD|dollars?|euros?)|"
            r"(?:USD|EUR|GBP|AUD|CAD)\s*\d[\d,.]*)"
            r"[^.;]{0,40}(?:for (?:any|each|every)|\bp(?:ayable|aid)\b|\bimposed\b))",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:no liquidated damages|no penalty|no penalties|"
            r"not (?:a|be (?:a|the)) penalty|not (?:be )?liquidated damages|"
            r"exclude(?:e?d)?|only|solely|cap(?:ed)?|limited to|"
            r"genuine pre[- ]?estimate|reasonable estimate|proportionate|"
            r"(?:neither party|no party)[^.;]{0,60}"
            r"(?:penalt|liquidated damage|forfeit|fixed charge)|"
            r"no (?:late fee|interest|damages)|"
            r"(?:shall|will|may) not (?:be|accrue|apply|incur))",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Liquidated-damages / penalty clause may allow disproportionate recovery",
        mitigation="Cap liquidated damages at a genuine pre-estimate of loss; avoid penalty-style per-day accrual without a bound.",
        description="Flags liquidated-damages or penalty clauses with disproportionate recovery risk.",
    ),
    # ------------------------------------------------------------------- data
    Rule(
        rule_id="R-DATA-5",
        dimension=Dimension.DATA,
        pattern=re.compile(
            r"(?:data|information)[^.]{0,60}"
            r"(?:(?:shall|may|will|can) (?:be )?(?:retained?|kept|maintain(?:s|ed)?|store[sd]?|preserv(?:e|es|ed|ing)?)|"
            r"(?:shall|may|will|can) (?:retain|keep|maintain|store|preserve))\b"
            r"[^.]{0,40}(?:after|following|upon) (?:the )?(?:termination|such termination|expiration|expiry)|"
            r"(?:after|following|upon) (?:the )?(?:termination(?: date)?|expiration|expiry|"
            r"such termination|termination of (?:this|the) agreement)"
            r"[^.;]{0,60}(?:provider|vendor|supplier|company|licensor)?[^.;]{0,60}"
            r"(?:shall|may|will|can|must|is (?:required|obligated) to)[^.;]{0,20}"
            r"(?:retain|keep|maintain|store|preserve)\s+(?:any |all |the )?(?:backup )?"
            r"(?:copies?|extracts?|records?|possession)?\s*(?:of\s+)?"
            r"(?:customer )?(?:personal )?(?:data|information)|"
            r"(?:shall|may|will|can) (?:retain|keep|maintain|store|preserve)\s+"
            r"(?:any |all |the )?(?:backup )?(?:copies?|extracts?|records?|possession)?\s*(?:of\s+)?"
            r"(?:customer )?(?:personal )?(?:data|information)"
            r"[^.]{0,40}(?:after|following|upon) (?:the )?(?:termination|such termination|expiration|expiry)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:require|required|obligat|as (?:required|needed)|in accordance with|"
            r"only for|solely|necessary to (?:comply|fulfil|fulfill)|legal obligation|"
            r"not (?:be )?(?:retained|kept)|"
            r"until[^.;]{0,40}(?:deleted|removed|purged|destroyed|returned)|"
            r"deleted[^.;]{0,30}within|removed[^.;]{0,30}within|returned[^.;]{0,30}within|"
            r"within (?:a period of|ninety|[0-9]+|thirty|sixty|seven|\w+)\s*(?:\(?\s*[0-9]+\s*\)?)?\s*"
            r"(?:ninety|[0-9]+)?\s*(?:days?|weeks?|months?|years?)[^.;]{0,30}(?:of|after|from) (?:termination|such termination)|"
            r"only to the extent (?:needed|necessary) to return|"
            r"return(?:ed)?[^.;]{0,30}on (?:the )?(?:customer'?s|data subject'?s)? request|"
            r"for a period of[^.;]{0,30}(?:days?|weeks?|months?|years?)|"
            r"after which (?:it|they|such (?:data|information))[^.;]{0,20}"
            r"(?:shall|will|may) (?:be )?(?:deleted|removed|purged|destroyed|returned|erased))",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Customer data may be retained after termination without a bounded, consent-limited basis",
        mitigation="Bound post-termination data retention to legal requirements, delete or return data within a defined window after term.",
        description="Flags unbounded post-termination retention of customer data.",
    ),
    Rule(
        rule_id="R-DATA-1",
        dimension=Dimension.DATA,
        pattern=re.compile(r"personal (?:data|information)|personally identifiable|\bpii\b", re.IGNORECASE),
        exclusion=re.compile(
            r"(?:gdpr|ccpa|data protection|privacy policy|dpa\b|data processing agreement|"
            r"standard contractual clauses|sccs?|adequacy (?:decision|determination|finding|adoption)|appropriate safeguards|"
            r"comply (?:with|ing)|consent|lawful basis|"
            r"(?:shall|will) only be (?:used|processed)|(?:only|solely) for the purpose|"
            r"purpose of performing|"
            r"solely to (?:provide|perform|fulfil|fulfill)|"
            r"(?:only|solely|strictly) (?:as|to)[^.]{0,20}(?:necessary|required) (?:for|to)|"
            r"for no other purpose|no other purpose|"
            r"no (?:transfer|processing|collection|sharing|disclosure)(?:s)? of (?:personal )?(?:data|information)|"
            r"no personal (?:data|information)[^.;]{0,20}(?:is|shall (?:be )?be|will be|may be)|"
            r"(?:shall|will|does|do|must|may) not (?:collect|process|use|share|store|obtain)\s+"
            r"personal (?:data|information)|"
            r"personal (?:data|information)[^.;]{0,20}"
            r"(?:is|are|shall|will|may|cannot?|must) not (?:be )?"
            r"(?:collected|processed|used|shared|stored|transferred|disclosed|provided)\b|"
            r"(?:neither|no (?:party|person))[^.;]{0,40}"
            r"(?:collect|process|use|share|store|obtain|transfer|disclose)"
            r"(?:[ ,]*(?:and |or )?(?:collect|process|use|share|store|obtain|transfer|disclose))*"
            r"\s+personal (?:data|information))",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Personal data is in scope; GDPR/CCPA obligations arise",
        mitigation="Confirm a lawful basis, a completed DPIA where needed, and a signed DPA annex with the counterparty.",
        description="Flags open-ended personal-data processing without GDPR/CCPA or DPA safeguards.",
    ),
    Rule(
        rule_id="R-DATA-2",
        dimension=Dimension.DATA,
        pattern=re.compile(
            r"(?:"
            # verb-led: {transfer...} {data} {outbound}
            r"(?:transfer(?:ring|red|s)?|transmit(?:ting|ted|s)?|process(?:ing|ed|es)?|"
            r"share(?:ing|d|s)?|store(?:ing|d|s)?|export(?:ing|ed|s)?|send(?:ing)?|"
            r"access(?:ing|ed)?|move(?:ing|d)?|host(?:ing|ed|s)?)"
            r"[^.]{0,20}(?:personal )?(?:data|information)[^.]{0,30}"
            r"(?:to|outside|abroad|from|in|at|into)"
            r"[^.]{0,20}(?:the )?"
            r"(?:united states|u\.?s\.?a?\.?\b|e\.?u\.?\b|eea\b|third[ -]countr(?:y|ies)|"
            r"foreign countr(?:y|ies)|affiliate(?:s)?|subprocessor(?:s)?|subsidiari(?:es|s)|"
            r"third[ -]parti(?:es|y)|outside|abroad|"
            r"\b(?:india|china|brazil|canada|mexico|japan|australia|singapore|south korea|"
            r"hong kong|israel|russia|south africa|philippines|indonesia|vietnam|malaysia|"
            r"thailand|taiwan|argentina|chile|colombia|nigeria|kenya|new zealand|turkey|"
            r"united arab emirates|u\.?a\.?e\.?\b|saudi arabia|qatar|pakistan|bangladesh|"
            r"egypt|morocco|ukraine)\b)"
            r")|(?:"
            # data-led: {data} {modal?} {passive verb} {outbound}
            r"(?:pii\b|(?:personal )?(?:data|information))[^.]{0,15}"
            r"(?:(?:is|are|shall|will|may|can|be|being|was|were)[^.]{0,5})?"
            r"(?:transferred|transmitted|processed|stored|shared|accessed|exported|sent|moved|"
            r"hosted|located|maintained|accessible)"
            r"[^.]{0,30}"
            r"(?:abroad|outside|"
            r"(?:to|from|in|at|into|with|outside)"
            r"[^.]{0,20}(?:the )?"
            r"(?:united states|u\.?s\.?a?\.?\b|e\.?u\.?\b|eea\b|third[ -]countr(?:y|ies)|"
            r"foreign countr(?:y|ies)|affiliate(?:s)?|subprocessor(?:s)?|subsidiari(?:es|s)|"
            r"third[ -]parti(?:es|y)|outside|abroad|"
            r"\b(?:india|china|brazil|canada|mexico|japan|australia|singapore|south korea|"
            r"hong kong|israel|russia|south africa|philippines|indonesia|vietnam|malaysia|"
            r"thailand|taiwan|argentina|chile|colombia|nigeria|kenya|new zealand|turkey|"
            r"united arab emirates|u\.?a\.?e\.?\b|saudi arabia|qatar|pakistan|bangladesh|"
            r"egypt|morocco|ukraine)\b)"
            r")"
            r")",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:shall (?:not|never) (?:be )?transferred?|"
            r"no (?:transfer|transfers) of (?:personal )?data[^.;]{0,50}shall|"
            r"shall not (?:occur|take place)|"
            r"(?:with|upon|subject to|in accordance with|pursuant to|following)\s+"
            r"(?:adequate|appropriate|standard contractual|sccs?|"
            r"the (?:standard )?(?:contractual clauses|sccs?)|"
            r"(?:an |the )?(?:eu|e\.?u\.?)? ?adequacy (?:decision|determination|finding|adoption))\b)",
            re.IGNORECASE,
        ),
        severity=35,
        reason="Cross-border / third-party data transfer without stated safeguards",
        mitigation="Add standard contractual clauses, adequacy findings, or equivalent transfer safeguards before any transfer.",
        description="Flags cross-border or third-party data transfers without stated safeguards.",
    ),
    Rule(
        rule_id="R-DATA-3",
        dimension=Dimension.DATA,
        pattern=re.compile(
            r"(?:process|use|sell|disclos|retain)(?:ing|es|ed|s)?"
            r"[^.]{0,30}data[^.]{0,20}"
            r"(?:for any (?:purpose|reason)(?: whatsoever)?|for any other purpose|"
            r"for any (?:and all|other) purposes?|"
            r"for (?:its|our) own(?: independent)?(?: business)? purposes|"
            r"for (?:marketing|advertising|commercial|unrelated) purposes|"
            r"for purposes? other than|unlimited|without limitation)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:necessary to comply|necessary for (?:compliance with|the purpose of complying)|"
            r"as (?:required|needed|mandated) by (?:applicable )?law|"
            r"required by (?:applicable )?(?:law|regulation)|"
            r"to meet (?:its|their) legal (?:and regulatory )?obligations?|"
            r"legal (?:and regulatory )?obligations?|"
            r"(?:shall|will|may|must)\s+not[^.;]{0,60}"
            r"(?:process|use|sell|disclos|retain)(?:ing|e|es|s)?"
            r"[^.;]{0,40}(?:for|to)\s+(?:any\s+)?purpose)",
            re.IGNORECASE,
        ),
        severity=25,
        reason="Data processing purpose may be too broad / unlimited",
        mitigation="Restrict processing to documented, purpose-limited activities and add data minimisation wording.",
        description="Flags overly broad or unlimited data-processing purposes.",
    ),
    # ------------------------------------------------------------------ export
    Rule(
        rule_id="R-EXP-1",
        dimension=Dimension.EXPORT,
        pattern=re.compile(r"\b(?:export(?:s|ed|ing)?|sanction(?:s|ed|ing)?|embargo(?:s|ed|ing)?|bribery|anti[- ]corruption|itar|deemed export(?:s|ed)?)\b", re.IGNORECASE),
        exclusion=re.compile(
            r"(?:comply (?:with|ing)|in compliance|"
            r"subject to (?:[^.]{0,20})?(?:export|sanction)s?|"
            r"responsible for obtaining|shall ensure|shall obtain|shall be responsible|counter[- ]sanctions|"
            r"applicable (?:export control|sanctions) laws|"
            r"with(out)? (?:the )?(?:prior |written ){0,2}"
            r"(?:authori[sz](?:ation)?|approval|permission|consent)|"
            r"require(?:s|d|ing)?[^.;]{0,40}(?:prior |written |express ){0,2}"
            r"(?:authori[sz](?:ation)?|approval|permission|consent|licen[cs]e)|"
            r"(?:re[- ]?export|export|transfer)\w*[^.;]{0,60}"
            r"\bwith(?: the)? [^.;]{0,25}(?:prior |written ){0,2}"
            r"(?:authori[sz](?:ation)?|approval|permission|consent)\b|"
            r"(?:may|shall|will|must|can) not (?:be )?(?:re[- ]?export(?:ed|ing)?|export(?:ed|ing)?)"
            r"[^.;]{0,60}without[^.;]{0,40}"
            r"(?:prior |written )?(?:authori[sz](?:ation)?|approval|permission|consent|licen[cs]e)|"
            r"(?:may|shall|will|must|can) not (?:be )?(?:fulfil(?:l)?(?:ed)?|export(?:ed)?|ship(?:ped)?|"
            r"sell|sold|deliver(?:ed)?|transfer(?:red)?|provide(?:d)?|distribute(?:d)?)"
            r"[^.;]{0,60}(?:to|into|in)[^.;]{0,30}(?:any )?"
            r"(?:sanctioned|prohibited|restricted)[^.;]{0,20}"
            r"(?:jurisdiction(?:s)?|countr(?:y|ies)|destination(?:s)?|territor(?:y|ies))|"
            r"\bno (?:orders?|fulfil(?:l)?ment|exports?|shipments?|sales?|deliver(?:ies|y))"
            r"[^.;]{0,40}(?:to|into)[^.;]{0,30}(?:any )?"
            r"(?:sanctioned|prohibited|restricted)[^.;]{0,20}"
            r"(?:jurisdiction(?:s)?|countr(?:y|ies)|destination(?:s)?|territor(?:y|ies))|"
            r"(?:excluding|excluded|exclude|except\b)[^.;]{0,80}"
            r"(?:regions?|territor(?:y|ies)|jurisdiction(?:s)?|countr(?:y|ies)|sanctioned)|"
            r"\bunder (?:a |the )?(?:valid |applicable |appropriate |current )?"
            r"(?:export|re[- ]?export) licen[cs]e\b)",
            re.IGNORECASE,
        ),
        severity=25,
        reason="Export/sanctions obligations appear but supporting controls are not visible in this clause",
        mitigation="Add a dedicated export-compliance clause and confirm which party owns export classification and licensing.",
        description="Prompts a check of export and sanctions obligations where trade terms appear.",
    ),
    Rule(
        rule_id="R-EXP-2",
        dimension=Dimension.EXPORT,
        condition=re.compile(
            r"export|sanction|embargo|"
            r"ship(?:s|ped|ping|ment|ments)?\b|deliver(?:ies|y|ed)?\b|"
            r"order(?:s|ed|ing)?\b|sold\b|sell\b|distribut(?:e|es|ed|ing|ion)\b|"
            r"fulfil(?:l)?(?:s|led|lment)?\b",
            re.IGNORECASE,
        ),
        pattern=re.compile(
            r"\b(cuba|iran|syria|north korea|crimea|sudan|myanmar)\b", re.IGNORECASE
        ),
        exclusion=re.compile(
            r"\bnot(?:\s+be)?\s+for\s+(?:delivery|sale|export|shipment|transfer)"
            r"(?:\s+(?:to|into|in))?[^.;]{0,40}\b(?:cuba|iran|syria|north korea|crimea|sudan|myanmar)\b|"
            r"(?:shall|will|must|may) not (?:be )?(?:export(?:ed)?|ship(?:ped)?|"
            r"transfer(?:red)?|sell|sold|deliver(?:ed)?|provide(?:d)?|distribute(?:d)?"
            r"|fulfil(?:l)?(?:ed)?)\b|"
            r"(?:are|is|were|do|does)\s+not\s+(?:be\s+)?(?:exported|shipped|transferred|sold|delivered|"
            r"provided|distributed|fulfil(?:l)?ed)\b|"
            r"\bno (?:export|shipment|transfer|sale|sales|fulfil(?:l)?ment)[^.;]{0,40}(?:to|into)\b|"
            r"(?:neither party|no party)[^.;]{0,40}(?:shall|will|may|must)?[^.;]{0,15}"
            r"(?:export(?:ed)?|ship(?:ped)?|transfer(?:red)?|sell|sold|deliver(?:ed)?|provide(?:d)?|"
            r"distribute(?:d)?|fulfil(?:l)?(?:ed)?)\b|"
            r"no (?:goods?|products?|software|technology|materials?|items?)\b"
            r"[^.;]{0,30}(?:shall|will|may)?[^.;]{0,10}be (?:exported|shipped|transferred|sold|delivered|"
            r"provided|distributed|fulfil(?:l)?ed)\b|"
            r"prohibit(?:s|ed)?\b|banned\b|"
            r"(?:comply(?:ing|ies)?|compliance|observe(?:s|d)?|consistent with)"
            r"[^.;]{0,80}(?:export|sanction|embargo|trade control)"
            r"[^.;]{0,80}(?:including|such as|applicable to|covering|that apply to|covering)"
            r"[^.;]{0,80}\b(?:cuba|iran|syria|north korea|crimea|sudan|myanmar)\b|"
            r"(?:excluding|excluded|exclude|except\b)[^.;]{0,80}"
            r"\b(?:cuba|iran|syria|north korea|crimea|sudan|myanmar)\b",
            re.IGNORECASE,
        ),
        severity=50,
        reason="References to a sanctioned jurisdiction without a compliance carve-out",
        mitigation="Remove any sanctioned-destination references or add an explicit sanctions-compliance and export-license carve-out.",
        description="Flags references to sanctioned jurisdictions without a compliance carve-out.",
    ),
    Rule(
        rule_id="R-EXP-3",
        dimension=Dimension.EXPORT,
        condition=re.compile(r"deliver|ship|supply|technology|software", re.IGNORECASE),
        pattern=re.compile(r"(?:re[- ]?export|diversion|end[- ]?use(?!r(?:s)?\b))", re.IGNORECASE),
        exclusion=re.compile(
            r"(?:require[sd]?[^.]{0,30}(?:authori[sz](?:ation)?|approval|permission|consent|licen[cs]e)|"
            r"obtain[^.]{0,30}authori[sz]|obtain[^.]{0,50}(?:approval|permission|consent|licen[cs]e)|"
            r"prior written authori[sz]|written authori[sz](?:ation)? (?:of|from|by)|"
            r"with (?:the )?(?:prior |written )?authori[sz](?:ation)?|"
            r"(?:re[- ]?export|export)\w*[^.;]{0,60}"
            r"\bwith(?: the)? [^.;]{0,25}(?:prior |written ){0,2}"
            r"(?:authori[sz](?:ation)?|approval|permission|consent)\b|"
            r"(?:may|shall|will|must|can) not (?:be )?(?:re[- ]?export(?:ed|ing)?|export(?:ed|ing)?)"
            r"[^.;]{0,40}without[^.;]{0,40}"
            r"(?:prior |written )?(?:authori[sz](?:ation)?|approval|permission|consent|licen[cs]e)|"
            r"subject to|comply|controls|restrictions|screening)",
            re.IGNORECASE,
        ),
        severity=30,
        reason="No export/re-export or diversion controls for deliverables",
        mitigation="Add re-export and end-use control language; require end-user screening and any relevant licences.",
        description="Flags missing re-export, diversion or end-use controls for deliverables.",
    ),
]

# Document-level absence checks: if the condition keyword/phrase appears but no
# protective term is present anywhere, flag the first matching paragraph.
ABSENCE_RULES: List[Rule] = [
    Rule(
        rule_id="R-DATA-4",
        dimension=Dimension.DATA,
        condition=re.compile(
            r"personal (?:data|information)|personally identifiable",
            re.IGNORECASE,
        ),
        pattern=re.compile(r"data (?:protection|controller|processor)|GDPR|CCPA|privacy policy|data processing agreement|DPA\b", re.IGNORECASE),
        exclusion=re.compile(
            r"no personal (?:data|information)[^.;]{0,20}(?:is|shall (?:be )?be|will be|may be)|"
            r"(?:shall|will|does|do|must|may) not (?:collect|process|use|share|store|obtain)\s+"
            r"personal (?:data|information)|"
            r"(?:neither|no (?:party|person))[^.;]{0,40}"
            r"(?:collect|process|use|share|store|obtain|transfer|disclose)"
            r"(?:[ ,]*(?:and |or )?(?:collect|process|use|share|store|obtain|transfer|disclose))*"
            r"\s+personal (?:data|information)|"
            r"personal (?:data|information)[^.;]{0,20}"
            r"(?:is|are|shall|will|may|cannot?|must) not (?:be )?"
            r"(?:collected|processed|used|shared|stored|transferred|disclosed|provided)\b",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Personal data handled but no data-protection / DPA terms found",
        mitigation="Add data-protection wording and a signed DPA (or flow-down) before any personal-data processing.",
        description="Flags a missing data-protection clause where personal data is handled.",
    ),
    Rule(
        rule_id="R-EXP-4",
        dimension=Dimension.EXPORT,
        condition=re.compile(
            r"export|sanctions?|embargo|"
            r"international\s+(?:sale|sales|shipment|shipments|transfer|transfers|trade|transaction)|"
            r"ship(?:ped|s|ping|ment|ments)[^.]{0,20}(?:internationally|abroad|overseas)|"
            r"deliver(?:s|ed|ing)?\b[^.]{0,20}(?:internationally|abroad|overseas)|"
            r"sold[^.]{0,20}(?:abroad|overseas|internationally)|"
            r"international(?:ly)?[^.]{0,15}(?:ship(?:ped|ping|ments?|ped)\b|trade\b)|"
            r"\babroad\b|\boverseas\b",
            re.IGNORECASE,
        ),
        pattern=re.compile(
            r"export control|compliance with (?:applicable )?(?:export|sanctions)|sanctions compliance|"
            r"export (?:licens|regulation|law)|sanctions (?:licens|regulation|law)|"
            r"re[- ]?export|diversion|export controls?|"
            r"(?:comply|compliance)[^.]{0,30}(?:controls?|measures?)|"
            r"(?:comply|compliance)[^.]{0,40}(?:with all applicable laws?|with applicable laws?)"
            r"[^.]{0,40}(?:including|such as)[^.]{0,40}(?:export|sanction)|"
            r"(?:laws?|regulations?|rules?)[^.]{0,30}"
            r"(?:including|covering|relating to|governing)[^.]{0,30}(?:export|sanction)|"
            r"no dealings?(?: with| in)[^.]{0,40}sanctioned|"
            r"(?:no|shall not)[^.]{0,40}business[^.]{0,40}(?:with|in)[^.]{0,40}sanctioned|"
            r"(?:neither party|no party|no person|no one)[^.;]{0,40}"
            r"(?:engage|deal|transact|do business)[^.;]{0,30}"
            r"(?:with|in)[^.;]{0,30}sanctioned|"
            r"(?:shall|will|must) not (?:engage in|conduct|enter into|do)[^.;]{0,40}"
            r"(?:business|dealings|transactions?)?[^.;]{0,20}(?:with|in)[^.;]{0,30}sanctioned",
            re.IGNORECASE,
        ),
        severity=25,
        reason="Export activities likely, but no export-compliance clause found",
        mitigation="Include an export-control and sanctions-compliance clause and allocate licence responsibility clearly.",
        description="Flags a missing export-compliance clause where export activity is likely.",
    ),
]

_DIMENSION_NAMES = {
    Dimension.COMMERCIAL: "Commercial risk",
    Dimension.LIABILITY: "Liability / legal risk",
    Dimension.DATA: "Data protection",
    Dimension.EXPORT: "Export compliance",
}

# Absence rules fire only when the topic is present but protective wording is
# missing; kept out of the plain regex-free serialisation below because they
# carry no literal match pattern of their own.
KIND_PARAGRAPH = "paragraph"
KIND_ABSENCE = "absence"


def rule_catalog() -> list[dict]:
    """Serialise the full rule set for the /api/rules handbook endpoint.

    Each entry is a plain dict (no compiled regex survives serialisation):
    id, dimension, severity, reason, mitigation, description and kind
    (paragraph vs document-level absence check). Pattern fragments are exposed
    as-is (source is public) so the handbook can explain what triggers a rule.
    """
    catalog: list[dict] = []
    for kind, rules in ((KIND_PARAGRAPH, RULES), (KIND_ABSENCE, ABSENCE_RULES)):
        for rule in rules:
            entry = {
                "rule_id": rule.rule_id,
                "dimension": rule.dimension.value,
                "dimension_label": _DIMENSION_NAMES[rule.dimension],
                "severity": rule.severity,
                "reason": rule.reason,
                "mitigation": rule.mitigation,
                "description": rule.description,
                "kind": kind,
                "has_condition": rule.condition is not None,
                "has_exclusion": rule.exclusion is not None,
            }
            if rule.pattern is not None:
                entry["pattern"] = rule.pattern.pattern
            if rule.condition is not None:
                entry["condition"] = rule.condition.pattern
            catalog.append(entry)
    return catalog


def _trim(text: str, limit: int = 240) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _pick(candidates: List[Penalty]) -> List[Penalty]:
    """Deterministically cap citations so a rule contributes <= N exemplars."""
    return candidates[:MAX_CITES_PER_RULE]


def _apply_paragraph_rules(
    paragraphs: List[str], rules: List[Rule]
) -> List[Penalty]:
    penalties: List[Penalty] = []
    for rule in rules:
        hits: List[Penalty] = []
        for i, para in enumerate(paragraphs):
            if looks_like_heading(para):
                continue
            normalized = para.casefold()
            if rule.condition is not None and not rule.condition.search(normalized):
                continue
            m = rule.pattern.search(normalized)
            if m and rule.exclusion and rule.exclusion.search(normalized):
                continue
            if m:
                hits.append(
                    Penalty(
                        dimension=rule.dimension,
                        reason=rule.reason,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        excerpt=_trim(para),
                        para_index=i,
                        keyword=m.group(0)[:80],
                        mitigation=rule.mitigation,
                    )
                )
        penalties.extend(_pick(hits))
    return penalties


def _apply_absence_rules(paragraphs: List[str], rules: List[Rule]) -> List[Penalty]:
    full = "\n".join(paragraphs).casefold()
    penalties: List[Penalty] = []
    for rule in rules:
        # Trigger only when the topic IS present but the protective term is not.
        m = rule.condition.search(full)
        if not m:
            continue
        if rule.exclusion and rule.exclusion.search(full):
            continue
        if rule.pattern.search(full):
            continue
        # Anchor the finding on a real body paragraph, never a heading, so the
        # excerpt points at the clause that raised the topic. If the topic only
        # appears inside headings (e.g. a "PERSONAL DATA" section title), fall
        # back to that heading as the closest verbatim source.
        body_hit = next(
            (
                i
                for i, p in enumerate(paragraphs)
                if not looks_like_heading(p) and rule.condition.search(p.casefold())
            ),
            None,
        )
        if body_hit is None:
            body_hit = next(
                (i for i, p in enumerate(paragraphs) if rule.condition.search(p.casefold())),
                None,
            )
        if body_hit is None:
            continue
        penalties.append(
            Penalty(
                dimension=rule.dimension,
                reason=rule.reason,
                rule_id=rule.rule_id,
                severity=rule.severity,
                excerpt=_trim(paragraphs[body_hit]),
                para_index=body_hit,
                keyword=None,
                mitigation=rule.mitigation,
            )
        )
    return penalties


def _level(score: int) -> RiskLevel:
    if score >= 66:
        return RiskLevel.HIGH
    if score >= 33:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _confidence(n_exemplars: int) -> float:
    """Deterministic confidence derived purely from evidence volume."""
    return round(min(0.95, 0.30 + 0.10 * n_exemplars), 2)


def score_document(paragraphs: List[str], document_id: str) -> RiskReport:
    """Compute a fully deterministic, explainable risk report."""
    penalties = _apply_paragraph_rules(paragraphs, RULES)
    penalties += _apply_absence_rules(paragraphs, ABSENCE_RULES)

    per_dim: dict[Dimension, int] = {}
    for dim in Dimension:
        per_dim[dim] = min(
            100, sum(p.severity for p in penalties if p.dimension is dim)
        )

    dimensions: List[DimensionScore] = []
    for dim in Dimension:
        raw = per_dim[dim]
        n_ex = sum(1 for p in penalties if p.dimension is dim)
        score = min(100.0, round(raw))
        dims = DimensionScore(
            dimension=dim,
            risk_level=_level(int(score)),
            raw_penalty=raw,
            normalized=score,
            confidence=_confidence(n_ex),
            reasons=[f"{p.reason} (excerpt #{p.para_index + 1})" for p in penalties if p.dimension is dim][:8]
            or [f"No material {_DIMENSION_NAMES[dim].lower()} concerns identified."],
        )
        dimensions.append(dims)

    weighted = sum(DIM_WEIGHTS[d.dimension] * d.normalized for d in dimensions)
    overall = int(round(weighted))

    # Determinism hash: content + engine version, so AC1 is machine-verifiable.
    digest = hashlib.sha256(
        "\n".join(paragraphs).encode("utf-8") + f"\nINCLUDES:{ENGINE_VERSION}".encode("utf-8")
    ).hexdigest()

    high = sum(1 for d in dimensions if d.risk_level is RiskLevel.HIGH)
    mid = sum(1 for d in dimensions if d.risk_level is RiskLevel.MEDIUM)
    n_pen = len(penalties)

    if high >= 3 or overall >= 66:
        summary = (
            f"High-risk agreement: {overall}/100 overall. {n_pen} findings across "
            f"{high} high-risk dimension(s) ({', '.join(_DIMENSION_NAMES[d.dimension] for d in dimensions if d.risk_level is RiskLevel.HIGH)}). "
            "Review termination, indemnity and data clauses together with the counterparty."
        )
    elif overall >= 33:
        summary = (
            f"Medium-risk agreement: {overall}/100 overall. {n_pen} findings; {mid} "
            "dimension(s) show moderate exposure. Targeted review recommended before signature."
        )
    else:
        summary = (
            f"Low-risk agreement: {overall}/100 overall. {n_pen} minor findings; "
            "standard protective wording appears to be in place."
        )

    return RiskReport(
        document_id=document_id,
        overall_score=overall,
        overall_level=_level(overall),
        dimensions=dimensions,
        penalties=penalties,
        summary=summary,
        deterministic_hash=digest,
    )
