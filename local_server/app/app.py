import datetime
import logging
from functools import wraps
from http import HTTPStatus

from flask import (
    Flask,
    redirect,
    current_app,
    make_response,
    render_template,
    abort,
    Blueprint,
    request,
    send_from_directory,
)
from flask_restful import Api, Resource

import local_server.common.rest as common_rest
from local_server.common.data_locator import DataLocator
from local_server.common.errors import DatasetAccessError, RequestException
from local_server.common.health import health_check
from local_server.common.utils.utils import path_join, Float32JSONEncoder
from local_server.data_common.matrix_loader import MatrixDataLoader

webbp = Blueprint("webapp", "local_server.common.web", template_folder="templates")

ONE_WEEK = 7 * 24 * 60 * 60


@webbp.route("/", methods=["GET"])
def dataset_index(url_dataroot=None, dataset=None):
    app_config = current_app.app_config
    server_config = app_config.server_config
    if dataset is None:
        if app_config.is_multi_dataset():
            return dataroot_index()
        else:
            location = server_config.single_dataset__datapath
    else:
        dataroot = None
        for key, dataroot_dict in server_config.multi_dataset__dataroot.items():
            if dataroot_dict["base_url"] == url_dataroot:
                dataroot = dataroot_dict["dataroot"]
                break
        if dataroot is None:
            abort(HTTPStatus.NOT_FOUND)
        location = path_join(dataroot, dataset)

    dataset_config = app_config.get_dataset_config(url_dataroot)
    scripts = dataset_config.app__scripts
    inline_scripts = dataset_config.app__inline_scripts

    try:
        cache_manager = current_app.matrix_data_cache_manager
        with cache_manager.data_adaptor(url_dataroot, location, app_config) as data_adaptor:
            data_adaptor.set_uri_path(f"{url_dataroot}/{dataset}")
            args = {"SCRIPTS": scripts, "INLINE_SCRIPTS": inline_scripts}
            return render_template("index.html", **args)

    except DatasetAccessError as e:
        return common_rest.abort_and_log(
            e.status_code, f"Invalid dataset {dataset}: {e.message}", loglevel=logging.INFO, include_exc_info=True
        )


@webbp.errorhandler(RequestException)
def handle_request_exception(error):
    return common_rest.abort_and_log(error.status_code, error.message, loglevel=logging.INFO, include_exc_info=True)


def get_data_adaptor(url_dataroot=None, dataset=None):
    config = current_app.app_config
    server_config = config.server_config
    dataset_key = None

    if dataset is None:
        datapath = server_config.single_dataset__datapath
    else:
        dataroot = None
        for key, dataroot_dict in server_config.multi_dataset__dataroot.items():
            if dataroot_dict["base_url"] == url_dataroot:
                dataroot = dataroot_dict["dataroot"]
                dataset_key = key
                break

        if dataroot is None:
            raise DatasetAccessError(f"Invalid dataset {url_dataroot}/{dataset}")
        datapath = path_join(dataroot, dataset)
        # path_join returns a normalized path.  Therefore it is
        # sufficient to check that the datapath starts with the
        # dataroot to determine that the datapath is under the dataroot.
        if not datapath.startswith(dataroot):
            raise DatasetAccessError(f"Invalid dataset {url_dataroot}/{dataset}")

    if datapath is None:
        return common_rest.abort_and_log(HTTPStatus.BAD_REQUEST, "Invalid dataset NONE", loglevel=logging.INFO)

    cache_manager = current_app.matrix_data_cache_manager
    return cache_manager.data_adaptor(dataset_key, datapath, config)


def requires_authentication(func):
    @wraps(func)
    def wrapped_function(self, *args, **kwargs):
        auth = current_app.auth
        if auth.is_user_authenticated():
            return func(self, *args, **kwargs)
        else:
            return make_response("not authenticated", HTTPStatus.UNAUTHORIZED)

    return wrapped_function


def rest_get_data_adaptor(func):
    @wraps(func)
    def wrapped_function(self, dataset=None):
        try:
            with get_data_adaptor(self.url_dataroot, dataset) as data_adaptor:
                data_adaptor.set_uri_path(f"{self.url_dataroot}/{dataset}")
                return func(self, data_adaptor)
        except DatasetAccessError as e:
            return common_rest.abort_and_log(
                e.status_code, f"Invalid dataset {dataset}: {e.message}", loglevel=logging.INFO, include_exc_info=True
            )

    return wrapped_function


def dataroot_test_index():
    # the following index page is meant for testing/debugging purposes
    data = '<!doctype html><html lang="en">'
    data += "<head><title>Hosted Cellxgene</title></head>"
    data += "<body><H1>Welcome to cellxgene</H1>"

    config = current_app.app_config
    server_config = config.server_config

    auth = server_config.auth
    if auth.is_valid_authentication_type():
        if server_config.auth.is_user_authenticated():
            data += f"<p>Logged in as {auth.get_user_id()} / {auth.get_user_name()} / {auth.get_user_email()}</p>"
        if auth.requires_client_login():
            if server_config.auth.is_user_authenticated():
                data += f"<p><a href='{auth.get_logout_url(None)}'>Logout</a></p>"
            else:
                data += f"<p><a href='{auth.get_login_url(None)}'>Login</a></p>"

    datasets = []
    for dataroot_dict in server_config.multi_dataset__dataroot.values():
        dataroot = dataroot_dict["dataroot"]
        url_dataroot = dataroot_dict["base_url"]
        locator = DataLocator(dataroot, region_name=server_config.data_locator__s3__region_name)
        for fname in locator.ls():
            location = path_join(dataroot, fname)
            try:
                MatrixDataLoader(location, app_config=config)
                datasets.append((url_dataroot, fname))
            except DatasetAccessError:
                # skip over invalid datasets
                pass

    data += "<br/>Select one of these datasets...<br/>"
    data += "<ul>"
    datasets.sort()
    for url_dataroot, dataset in datasets:
        data += f"<li><a href={url_dataroot}/{dataset}>{dataset}</a></li>"
    data += "</ul>"
    data += "</body></html>"

    return make_response(data)


def dataroot_index():
    # Handle the base url for the cellxgene server when running in multi dataset mode
    config = current_app.app_config
    if not config.server_config.multi_dataset__index:
        abort(HTTPStatus.NOT_FOUND)
    elif config.server_config.multi_dataset__index is True:
        return dataroot_test_index()
    else:
        return redirect(config.server_config.multi_dataset__index)


class HealthAPI(Resource):
    def get(self):
        config = current_app.app_config
        return health_check(config)


class DatasetResource(Resource):
    """Base class for all Resources that act on datasets."""

    def __init__(self, url_dataroot):
        super().__init__()
        self.url_dataroot = url_dataroot


class SchemaAPI(DatasetResource):
    # TODO @mdunitz separate dataset schema and user schema
    @rest_get_data_adaptor
    def get(self, data_adaptor):
        return common_rest.schema_get(data_adaptor)


class ConfigAPI(DatasetResource):
    @rest_get_data_adaptor
    def get(self, data_adaptor):
        return common_rest.config_get(current_app.app_config, data_adaptor)


class UserInfoAPI(DatasetResource):
    @rest_get_data_adaptor
    def get(self, data_adaptor):
        return common_rest.userinfo_get(current_app.app_config, data_adaptor)


class AnnotationsObsAPI(DatasetResource):
    @rest_get_data_adaptor
    def get(self, data_adaptor):
        return common_rest.annotations_obs_get(request, data_adaptor)

    @requires_authentication
    @rest_get_data_adaptor
    def put(self, data_adaptor):
        return common_rest.annotations_obs_put(request, data_adaptor)


class AnnotationsVarAPI(DatasetResource):
    @rest_get_data_adaptor
    def get(self, data_adaptor):
        return common_rest.annotations_var_get(request, data_adaptor)


class DataVarAPI(DatasetResource):
    @rest_get_data_adaptor
    def put(self, data_adaptor):
        return common_rest.data_var_put(request, data_adaptor)

    @rest_get_data_adaptor
    def get(self, data_adaptor):
        return common_rest.data_var_get(request, data_adaptor)


class ColorsAPI(DatasetResource):
    @rest_get_data_adaptor
    def get(self, data_adaptor):
        return common_rest.colors_get(data_adaptor)


class DiffExpObsAPI(DatasetResource):
    @rest_get_data_adaptor
    def post(self, data_adaptor):
        return common_rest.diffexp_obs_post(request, data_adaptor)


class LayoutObsAPI(DatasetResource):
    @rest_get_data_adaptor
    def get(self, data_adaptor):
        return common_rest.layout_obs_get(request, data_adaptor)

    @rest_get_data_adaptor
    def put(self, data_adaptor):
        return common_rest.layout_obs_put(request, data_adaptor)


def get_api_base_resources(bp_base):
    """Add resources that are accessed from the api url"""
    api = Api(bp_base)

    # Diagnostics routes
    api.add_resource(HealthAPI, "/health")
    return api


def get_api_dataroot_resources(bp_dataroot, url_dataroot=None):
    """Add resources that refer to a dataset"""
    api = Api(bp_dataroot)

    def add_resource(resource, url):
        """convenience function to make the outer function less verbose"""
        api.add_resource(resource, url, resource_class_args=(url_dataroot,))

    # Initialization routes
    add_resource(SchemaAPI, "/schema")
    add_resource(ConfigAPI, "/config")
    add_resource(UserInfoAPI, "/userinfo")
    # Data routes
    add_resource(AnnotationsObsAPI, "/annotations/obs")
    add_resource(AnnotationsVarAPI, "/annotations/var")
    add_resource(DataVarAPI, "/data/var")
    # Display routes
    add_resource(ColorsAPI, "/colors")
    # Computation routes
    add_resource(DiffExpObsAPI, "/diffexp/obs")
    add_resource(LayoutObsAPI, "/layout/obs")
    return api


class Server:
    @staticmethod
    def _before_adding_routes(app, app_config):
        """ will be called before routes are added, during __init__.  Subclass protocol """
        pass

    def __init__(self, app_config):
        self.app = Flask(__name__, static_folder=None)
        self._before_adding_routes(self.app, app_config)
        self.app.json_encoder = Float32JSONEncoder
        server_config = app_config.server_config

        # enable session data
        self.app.permanent_session_lifetime = datetime.timedelta(days=50 * 365)

        # Config
        secret_key = server_config.app__flask_secret_key
        self.app.config.update(SECRET_KEY=secret_key)

        self.app.register_blueprint(webbp)

        api_version = "/api/v0.2"
        api_path = "/"

        bp_base = Blueprint("bp_base", __name__, url_prefix=api_path)
        base_resources = get_api_base_resources(bp_base)
        self.app.register_blueprint(base_resources.blueprint)

        if app_config.is_multi_dataset():
            # NOTE:  These routes only allow the dataset to be in the directory
            # of the dataroot, and not a subdirectory.  We may want to change
            # the route format at some point
            for dataroot_dict in server_config.multi_dataset__dataroot.values():
                url_dataroot = dataroot_dict["base_url"]
                bp_dataroot = Blueprint(
                    f"api_dataset_{url_dataroot}",
                    __name__,
                    url_prefix=f"{api_path}/{url_dataroot}/<dataset>" + api_version,
                )
                dataroot_resources = get_api_dataroot_resources(bp_dataroot, url_dataroot)
                self.app.register_blueprint(dataroot_resources.blueprint)

                self.app.add_url_rule(
                    f"/{url_dataroot}/<dataset>",
                    f"dataset_index_{url_dataroot}",
                    lambda dataset, url_dataroot=url_dataroot: dataset_index(url_dataroot, dataset),
                    methods=["GET"],
                )
                self.app.add_url_rule(
                    f"/{url_dataroot}/<dataset>/",
                    f"dataset_index_{url_dataroot}/",
                    lambda dataset, url_dataroot=url_dataroot: dataset_index(url_dataroot, dataset),
                    methods=["GET"],
                )
                self.app.add_url_rule(
                    f"/{url_dataroot}/<dataset>/static/<path:filename>",
                    f"static_assets_{url_dataroot}",
                    view_func=lambda dataset, filename: send_from_directory("../common/web/static", filename),
                    methods=["GET"],
                )

        else:
            bp_api = Blueprint("api", __name__, url_prefix=f"{api_path}{api_version}")
            resources = get_api_dataroot_resources(bp_api)
            self.app.register_blueprint(resources.blueprint)
            self.app.add_url_rule(
                "/static/<path:filename>",
                "static_assets",
                view_func=lambda filename: send_from_directory("../common/web/static", filename),
                methods=["GET"],
            )

        self.app.matrix_data_cache_manager = server_config.matrix_data_cache_manager
        self.app.app_config = app_config

        auth = server_config.auth
        self.app.auth = auth
        if auth.requires_client_login():
            auth.add_url_rules(self.app)
        auth.complete_setup(self.app)
