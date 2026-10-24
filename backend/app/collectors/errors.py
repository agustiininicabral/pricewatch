class StoreAdapterError(Exception):
    """Base de errores esperables al consultar un adaptador."""


class UnsupportedURLError(StoreAdapterError):
    """La URL no pertenece a un origen admitido por el adaptador."""


class ExtractionFailedError(StoreAdapterError):
    """El documento disponible no tiene una estructura extraíble válida."""


class InvalidPriceError(ExtractionFailedError):
    """El precio de origen está malformado, es negativo o no es positivo."""


class SourceUnavailableError(StoreAdapterError):
    """El archivo fuente local no se pudo leer."""
