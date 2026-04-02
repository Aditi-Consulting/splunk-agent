from app.utility.llm import call_llm_for_json
from app.utility.summary_tracker import capture_node_execution


def troubleshoot_node(state):
    """
    LLM-powered node that identifies where exactly the issue occurred —
    which class/service and what operation was being performed.
    Keeps output short and UI-friendly.
    """
    try:
        alerts = state.get("alerts", [])
        alert = alerts[0] if alerts else {}
        ticket = alert.get("ticket", "")
        issue_type = alert.get("issue_type", "unknown")

        prompt = (
            "You are a technical troubleshooter. Given the alert below, identify:\n"
            "1. Which class, method, or service has the issue (location)\n"
            "2. What operation was being performed when it occurred (1 concise sentence)\n\n"
            "Be specific and brief. Return ONLY valid JSON with no extra text:\n"
            '{{"location": "...", "context": "..."}}\n\n'
            f"Alert: {ticket}\n"
            f"Issue Type: {issue_type}"
        )

        result = call_llm_for_json(prompt)

        if "__error__" in result:
            full_result = {
                "location": "Unknown location",
                "context": "Could not determine context automatically."
            }
        else:
            full_result = {
                "location": result.get("location", "Unknown"),
                "context": result.get("context", "No context available.")
            }

        state["troubleshooting"] = full_result
        state = capture_node_execution(state, "troubleshoot_the_issue", result=full_result)
        return state

    except Exception as e:
        state = capture_node_execution(state, "troubleshoot_the_issue", error=str(e))
        return state
