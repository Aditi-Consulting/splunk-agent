from app.utility.summary_tracker import capture_node_execution


def suggestions_node(state):
    """
    Returns hardcoded fix steps for demo purposes.
    Steps are stored as individual array items so the UI renders each on its own line.
    """
    try:
        fix_steps = [
            "Review the UserService class code to identify potential null references in the getAllUsers method.",
            "Implement null checks or default values to handle cases where user data may not be available.",
            "Test the updated code locally to ensure the null pointer exception is resolved.",
            "Deploy the updated code to the production environment and monitor the /api/users endpoint for successful responses.",
        ]

        full_result = {
            "fix_steps": fix_steps,
            "total_steps": len(fix_steps)
        }

        state["fix_suggestions"] = full_result
        state = capture_node_execution(state, "suggestions_for_fix", result=full_result)
        return state

    except Exception as e:
        state = capture_node_execution(state, "suggestions_for_fix", error=str(e))
        return state
