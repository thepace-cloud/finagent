"""Conservative numeric and product-source checks; not a semantic entailment judge."""
import re


def numbers(text):
    for a,b in (("一年","1年"),("五年","5年"),("一个月","1个月"),("两倍","2倍")):
        text=text.replace(a,b)
    result=set()
    for number,unit in re.findall(r"(\d+(?:\.\d+)?)\s*(万元|元|年|个月|%|倍)?",text):
        value=float(number)
        if unit=="万元":
            value*=10000
            unit="元"
        result.add((value,unit))
    return result


def support_errors(answer,passages):
    by_id={p["id"]:p for p in passages}
    errors=[]
    for field,value in answer.get("facts",{}).items():
        if field=="monthly_payment":
            continue
        refs=answer.get("evidence",{}).get(field,[])
        quotes=answer.get("quotes",{}).get(field,[])
        quotes=[quotes] if isinstance(quotes,str) else quotes
        if not isinstance(refs,list) or not isinstance(quotes,list):
            continue  # Shape errors are handled by ground().
        if "." in field and any(by_id.get(r,{}).get("doc_id")!=field.split(".")[0] for r in refs):
            errors.append(field+":product_source_mismatch")
        claimed=numbers(str(value))
        supported=numbers(" ".join(q for q in quotes if isinstance(q,str)))
        if not claimed.issubset(supported):
            errors.append(field+":numeric_value_not_in_quote")
    return errors
