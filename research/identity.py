"""IDENTITY resolution: official domain + owned channels (Section 19)."""
from research.llm import call_llm
from research.tavily import tavily_search
from research import schemas, urls_util


def resolve_identity(run):
    """Return (domain|None, owned_profile_urls, owned_handles).

    URL input derives the domain deterministically (no LLM). Name input asks
    call_llm("IDENTITY"), aided by a Tavily lookup. Exceptions bubble up and are
    treated as non-fatal by the caller (Section 5.4).
    """
    if run.input_kind == "url":
        return urls_util.registrable_domain(run.input_text), [], []
    hints = [h["url"] for h in
             tavily_search(f"{run.input_text} official website", 36, 5)]
    prompt = (f'Company: "{run.input_text}". Candidate URLs: {hints}. '
              'Return JSON {official_domain, owned_profile_urls, '
              'owned_social_handles, confidence, matched}.')
    data = schemas.parse_identity(
        call_llm("IDENTITY", [{"role": "user", "content": prompt}],
                 run_id=run.id, json_object=True)["content"])
    if not data["matched"] or not data["official_domain"]:
        return None, data["owned_profile_urls"], data["owned_social_handles"]
    return (urls_util.registrable_domain(data["official_domain"]),
            data["owned_profile_urls"], data["owned_social_handles"])
