import logging
import coloredlogs

def setup_logging():
    """Configure logging for the application."""
    logger = logging.getLogger(__name__)
    
    # Configure coloredlogs
    coloredlogs.install(
        level='INFO',
        logger=logger,
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level_styles={
            'debug': {'color': 'green'},
            'info': {'color': 'white'},
            'warning': {'color': 'yellow'},
            'error': {'color': 'red'},
            'critical': {'color': 'red', 'bold': True},
        },
        field_styles={
            'asctime': {'color': 'green'},
            'levelname': {'color': 'blue', 'bold': True},
            'name': {'color': 'magenta'},
        }
    )
    
    return logger
