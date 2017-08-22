.. _configuration:

Configuration
=============




.. tabularcolumns:: |p{6.5cm}|p{8.5cm}|

================================= =========================================
``WEBLAB_USERNAME``               WebLab-Deusto credentials. It is not the
                                  username of the new user: it represents 
                                  the system itself (e.g., the WebLab-Deusto
                                  system calling). **Mandatory**
``WEBLAB_PASSWORD``               WebLab-Deusto credentials. Read also 
                                  ``WEBLAB_USERNAME``. **Mandatory**
``WEBLAB_CALLBACK_URL``           **weblablib** creates a set or URLs for 
                                  receiving methods directly by the user. 
                                  This methods must be publicly available by
                                  the student. It can be ``/mylab/callback``.
                                  **Mandatory** (unless you provide 
                                  ``callback_url`` parameter to the ``WebLab``
                                  constructor).
``WEBLAB_BASE_URL``               If you want to start /weblab/sessions 
                                  somewhere else (e.g., ``/mylab``), you can
                                  configure it here.
================================= =========================================
