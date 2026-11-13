async def _execute_tool_chain(
    task: TaskState, plan: List[Dict[str, Any]]
) -> Dict[str, Any]:
    task.status = "running"
    for idx, step in enumerate(plan, start=1):
        tool = step.get("tool")
        args = step.get("args", {})
        if STOP_REQUESTED:
            task.status = "stopped"
            err = "Emergency stop requested"
            task.error = err
            _log_event(task, "task.stopped", tool, step.get("action", ""), err, False)
            return {"status": "stopped", "error": err}
        risk = classify_tool_call(tool, args, task.user_command)
        if should_ask(1.0, risk):
            _apply_confirmation(task, risk, tool, args)
        if step.get("action") == "verify":
            await _verify_step(task, expected=step.get("expected"))
            continue
        result = await _async_tool_call(task, tool, args)
        if isinstance(result, str) and result.startswith("Error"):
            task.error = result
            task.status = "failed"
            return {"status": "failed", "error": result}
        if idx >= MAX_AUTO_STEPS:
            task.status = "completed"
            task.result = "Max automation steps reached"
            return {"status": "completed", "result": "Max automation steps reached"}
    task.status = "completed"
    task.result = "Task completed"
    return {"status": "completed", "result": "Task completed"}


def reset_stop_flag() -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = False


def request_stop() -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def is_stop_requested() -> bool:
    return STOP_REQUESTED
