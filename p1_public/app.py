"""Separate public-corpus API; does not change the existing V5 service."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel, Field
from engine import Engine, calculator, generate, ground
from support import support_errors


@asynccontextmanager
async def lifespan(app):
    app.state.engine=Engine()
    yield


app=FastAPI(title="FinAgent public evidence research preview",lifespan=lifespan)


class Request(BaseModel):
    question:str=Field(min_length=1,max_length=3000)
    requested_fields:list[str]=Field(default_factory=list,max_length=12)


@app.get("/health")
def health():
    return {"status":"ok","sources":len(app.state.engine.sources)}


@app.post("/answer")
def answer(request:Request):
    engine=app.state.engine
    tool=calculator(request.question)
    if tool is not None:
        return {"answer":tool,"trace":{"strategy":"calculator"},"sources":[]}
    hits,plan=engine.retrieve(request.question,"decomposed",k=6)
    context=[engine.passages[p] for _,p in hits]
    result=generate(request.question,request.requested_fields,context)
    errors=ground(result,context)
    if not errors:
        errors+=support_errors(result,context)
    if errors:
        result={"status":"insufficient","facts":{},"evidence":{},"quotes":{},"missing":[],"validation_errors":errors}
    cited={ref for refs in result.get("evidence",{}).values() for ref in refs}
    return {"answer":result,"trace":plan,"sources":[p for p in context if p["id"] in cited]}
