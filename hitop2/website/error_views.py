from django.shortcuts import render


def _render_error(request, status, title, message):
    return render(
        request,
        f"errors/{status}.html",
        {
            "error_status": status,
            "error_title": title,
            "error_message": message,
        },
        status=status,
    )


def bad_request(request, exception=None):
    return _render_error(
        request,
        400,
        "Pedido inválido",
        "Não foi possível processar este pedido. Verifique os dados e tente novamente.",
    )


def permission_denied(request, exception=None):
    return _render_error(
        request,
        403,
        "Acesso não autorizado",
        "Não tem permissão para aceder a esta página.",
    )


def page_not_found(request, exception=None):
    return _render_error(
        request,
        404,
        "Página não encontrada",
        "A página que procura não existe, foi removida ou o endereço está incorreto.",
    )


def server_error(request):
    return _render_error(
        request,
        500,
        "Ocorreu um erro",
        "Não foi possível concluir o pedido. Tente novamente dentro de alguns instantes.",
    )


def csrf_failure(request, reason=""):
    return _render_error(
        request,
        403,
        "Sessão expirada",
        "Atualize a página e volte a enviar o formulário.",
    )
