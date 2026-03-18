from pathlib import Path

from app import __version__ as APP_VERSION


def build_release_guide_filename(version: str = APP_VERSION, arch_suffix: str = "win64") -> str:
    clean_version = str(version or "").strip()
    return f"Compensacoes-v{clean_version}-{arch_suffix}-guide.txt"


def build_release_guide(
    *,
    version: str = APP_VERSION,
    primary_filename: str,
    hash_filename: str,
    signed: bool = False,
    signature_mode: str = "",
    homepage_url: str = "",
    checksum_script_name: str = "verify_release_checksum.ps1",
    signature_script_name: str = "verify_signature.ps1",
) -> str:
    artifact_name = Path(primary_filename).name
    checksum_name = Path(hash_filename).name
    signature_mode_text = str(signature_mode or "").strip() or "nao informado"
    homepage = str(homepage_url or "").strip()

    lines = [
        f"Compensacoes {version}",
        "",
        "Guia rapido para distribuicao e validacao da release.",
        "",
        "Arquivos esperados:",
        f"- Artefato principal: {artifact_name}",
        f"- Checksum SHA-256: {checksum_name}",
        f"- Script de verificacao: {checksum_script_name}",
        "",
        "Como validar a integridade no PowerShell:",
        f"1. Baixe {artifact_name} e {checksum_name} para a mesma pasta.",
        f"2. Rode: .\\{checksum_script_name} -ArtifactPath .\\{artifact_name}",
        "3. Confirme que o hash calculado bate com o arquivo .sha256 publicado.",
        "",
    ]

    if signed:
        lines.extend(
            [
                "Assinatura digital:",
                f"- Esta release foi assinada digitalmente ({signature_mode_text}).",
                f"- Para validar a assinatura, rode: .\\{signature_script_name} -Path .\\{artifact_name}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "Assinatura digital:",
                "- Esta release foi distribuida sem assinatura digital do Windows.",
                "- Em uso restrito, valide sempre o checksum antes de instalar ou executar.",
                "",
                "Se o Windows exibir SmartScreen:",
                "- Continue somente se o arquivo veio da fonte esperada e o checksum conferiu.",
                "- Para distribuicao publica ampla, considere habilitar code signing no futuro.",
                "",
            ]
        )

    if homepage:
        lines.extend(
            [
                f"Suporte/Origem oficial: {homepage}",
                "",
            ]
        )

    lines.extend(
        [
            "Observacao:",
            "- O app pode funcionar sem assinatura, mas o Windows pode mostrar avisos adicionais.",
        ]
    )
    return "\n".join(lines) + "\n"
