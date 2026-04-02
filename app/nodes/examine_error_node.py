from app.utility.llm import call_llm_for_json
from app.utility.summary_tracker import capture_node_execution


def examine_error_node(state):
    """
    LLM-powered node that identifies the error type and reason it occurred.
    Keeps output short and UI-friendly.
    """
    try:
        alerts = state.get("alerts", [])
        alert = alerts[0] if alerts else {}
        ticket = alert.get("ticket", "")
        issue_type = alert.get("issue_type", "unknown")
        severity = alert.get("severity", "medium")

        prompt = (
            "You are a technical error analyst. Given the alert below, identify:\n"
            "1. The error type (short name, e.g. NullPointerException)\n"
            "2. Why this error typically occurs (1 concise sentence)\n\n"
            "Be brief and technical. Return ONLY valid JSON with no extra text:\n"
            '{{"error_type": "...", "reason": "..."}}\n\n'
            f"Alert: {ticket}\n"
            f"Issue Type: {issue_type}\n"
            f"Severity: {severity}"
        )

        result = call_llm_for_json(prompt)

        if "__error__" in result:
            full_result = {
                "error_type": issue_type,
                "reason": "Could not analyze error automatically."
            }
        else:
            full_result = {
                "error_type": result.get("error_type", issue_type),
                "reason": result.get("reason", "No analysis available.")
            }

        state["error_analysis"] = full_result
        state = capture_node_execution(state, "examine_the_error", result=full_result)
        return state

    except Exception as e:
        state = capture_node_execution(state, "examine_the_error", error=str(e))
        return state
