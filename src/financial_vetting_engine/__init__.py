def main() -> None:
    import uvicorn

    uvicorn.run(
        "financial_vetting_engine.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


__all__ = ["main"]
