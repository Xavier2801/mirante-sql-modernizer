"""
Módulo de Avaliação Automatizada da Qualidade da Migração (Evaluation Suite).
Calcula scores objetivos de conformidade sintática, precisão financeira e mitigação de riscos.
"""
import ast
import json
from pathlib import Path
from typing import Dict, Any, List


class PipelineEvaluator:
    """Avaliador objetivo baseado em AST e análise estática de código gerado."""

    def evaluate_code(self, source_sql: str, generated_code: str, risk_flags: List[str]) -> Dict[str, Any]:
        """Avalia um único par de SQL legado e Python 3.14 gerado."""
        checks = {
            "ast_valid": False,
            "has_executable_defs": False,
            "financial_precision_compliant": True,
            "for_update_mitigated": True,
            "cursor_eliminated": True,
        }
        score = 0.0
        details = []

        if not generated_code or not generated_code.strip():
            return {
                "overall_score": 0.0,
                "checks": checks,
                "details": ["Código gerado vazio ou nulo."]
            }

        # 1. Validação de AST (Peso 40%)
        try:
            tree = ast.parse(generated_code)
            checks["ast_valid"] = True
            score += 0.40

            funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if funcs:
                checks["has_executable_defs"] = True
                score += 0.20
            else:
                details.append("Nenhuma função/método definido no arquivo.")
        except SyntaxError as e:
            details.append(f"Erro de sintaxe Python AST: {e.msg} (linha {e.lineno})")

        # 2. Conformidade Financeira (Decimal vs float) (Peso 20%)
        has_numeric = "NUMERIC" in source_sql.upper() or "DECIMAL" in source_sql.upper()
        if has_numeric:
            has_decimal_import = "Decimal" in generated_code or "decimal" in generated_code
            has_float_usage = "float(" in generated_code or ": float" in generated_code
            if has_decimal_import and not has_float_usage:
                score += 0.20
            else:
                checks["financial_precision_compliant"] = False
                details.append("Risco financeiro: Esperado uso estrito de Decimal sem uso de float primitivo.")
        else:
            score += 0.20

        # 3. Mitigação de Riscos de Concorrência e Performance (Peso 20%)
        risk_score = 0.20
        # Caso FOR UPDATE
        if any("FOR_UPDATE" in r for r in risk_flags):
            if "with_for_update" in generated_code or "FOR UPDATE" in generated_code:
                pass
            else:
                checks["for_update_mitigated"] = False
                risk_score -= 0.10
                details.append("Risco de Concorrência: FOR UPDATE identificado no legado mas sem with_for_update() no código gerado.")

        # Caso CURSOR
        if any("CURSOR" in r for r in risk_flags):
            # Não deve ter 'while' repetitivo com queries avulsas
            if "cursor" in generated_code.lower() and "fetch" in generated_code.lower():
                checks["cursor_eliminated"] = False
                risk_score -= 0.10
                details.append("Risco N+1: Cursor iterativo mantido no Python em vez de query set-based agregada.")

        score += max(0.0, risk_score)

        return {
            "overall_score": round(score, 2),
            "checks": checks,
            "details": details
        }

    def evaluate_output_directory(self, output_dir: Path) -> Dict[str, Any]:
        """Avalia todos os anexos já persistidos na pasta output/."""
        json_reports = list(output_dir.glob("*_report.json"))
        if not json_reports:
            return {"error": "Nenhum relatório encontrado em output/"}

        results = []
        total_score = 0.0
        ast_passed = 0

        for report_file in json_reports:
            with open(report_file, "r", encoding="utf-8") as f:
                report_data = json.load(f)

            base_name = report_file.stem.replace("_report", "")
            py_file = output_dir / f"{base_name}.py"
            generated_code = py_file.read_text(encoding="utf-8") if py_file.exists() else ""

            risk_flags = report_data.get("risk_flags", [])
            # Heurística para checagem do SQL original
            source_sql = report_data.get("procedure_name", "") + " NUMERIC FOR UPDATE CURSOR"

            eval_res = self.evaluate_code(
                source_sql=source_sql,
                generated_code=generated_code,
                risk_flags=risk_flags
            )

            if eval_res["checks"]["ast_valid"]:
                ast_passed += 1

            total_score += eval_res["overall_score"]
            results.append({
                "module": base_name,
                "score": eval_res["overall_score"],
                "checks": eval_res["checks"],
                "details": eval_res["details"]
            })

        count = len(results)
        return {
            "total_modules_evaluated": count,
            "ast_pass_rate": f"{(ast_passed / count) * 100:.1f}%" if count else "0%",
            "mean_pipeline_score": round(total_score / count, 2) if count else 0.0,
            "modules": results
        }