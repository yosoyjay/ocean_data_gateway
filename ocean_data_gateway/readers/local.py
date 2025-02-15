import logging
import os
import intake
import pandas as pd
import hashlib
from joblib import Parallel, delayed
import multiprocessing
import pathlib
import ocean_data_gateway as odg


# Capture warnings in log
logging.captureWarnings(True)

# formatting for logfile
formatter = logging.Formatter('%(asctime)s %(message)s','%a %b %d %H:%M:%S %Z %Y')
log_name = 'reader_local'
loglevel=logging.WARNING
path_logs_reader = odg.path_logs.joinpath(f'{log_name}.log')

# set up logger file
handler = logging.FileHandler(path_logs_reader)
handler.setFormatter(formatter)
logger_local = logging.getLogger(log_name)
logger_local.setLevel(loglevel)
logger_local.addHandler(handler)

# this can be queried with
# search.LocalReader.reader
reader = 'local'



class LocalReader:


    def __init__(self, parallel=True, catalog_name=None, filenames=None, kw=None):

        self.parallel = parallel

        if catalog_name is None:
            name = f'{pd.Timestamp.now().isoformat()}'
            hash_name = hashlib.sha256(name.encode()).hexdigest()[:7]
            path_catalog = odg.path_catalogs.joinpath(f'catalog_{hash_name}.yml')
            self.catalog_name = path_catalog#.name
        else:
            self.catalog_name = catalog_name
            # if catalog_name already exists, read it in to save time
            self.catalog

        if (filenames is not None) and (not isinstance(filenames, list)):
            filenames = [filenames]
        self.filenames = filenames

        if kw is None:
            kw = {'min_time': '1900-01-01', 'max_time': '2100-12-31'}

        self.kw = kw

        if (filenames == None) and (catalog_name == None):
            self._dataset_ids = []
            logger_local.warning('no datasets for LocalReader with catalog_name {catalog_name} and filenames {filenames}.')

        # name
        self.name = 'local'

        self.reader = 'LocalReader'



    def write_catalog(self):

        # if the catalog already exists, don't do this
        if os.path.exists(self.catalog_name):
            return

        else:
            lines = 'sources:\n'

            for filename in self.filenames:

                if 'csv' in filename:
                    file_intake = intake.open_csv(filename)
                    data = file_intake.read()
                    metadata = {'variables': list(data.columns.values),
                                'geospatial_lon_min': float(data['longitude'].min()),
                                'geospatial_lat_min': float(data['latitude'].min()),
                                'geospatial_lon_max': float(data['longitude'].max()),
                                'geospatial_lat_max': float(data['latitude'].max()),
                                'time_coverage_start': data['time'].min(),
                                'time_coverage_end': data['time'].max()}
                    file_intake.metadata = metadata

                elif 'nc' in filename:
                    file_intake = intake.open_netcdf(filename)
                    data = file_intake.read()
                    coords = list(data.coords.keys())
                    timekey = [coord for coord in coords
                                if ('time' in data[coord].attrs.values())
                                or ('T' in data[coord].attrs.values())]
                    if len(timekey) > 0:
                        timekey = timekey[0]
                        time_coverage_start = str(data[timekey].min().values)
                        time_coverage_end = str(data[timekey].max().values)
                    else:
                        time_coverage_start = ''
                        time_coverage_end = ''
                    lonkey = [coord for coord in coords
                                if ('lon' in data[coord].attrs.values())
                                or ('X' in data[coord].attrs.values())]
                    if len(lonkey) > 0:
                        lonkey = lonkey[0]
                        geospatial_lon_min = float(data[lonkey].min())
                        geospatial_lon_max = float(data[lonkey].max())
                    else:
                        geospatial_lon_min = ''
                        geospatial_lon_max = ''
                    latkey = [coord for coord in coords
                                if ('lat' in data[coord].attrs.values())
                                or ('Y' in data[coord].attrs.values())]
                    if len(latkey) > 0:
                        latkey = latkey[0]
                        geospatial_lat_min = float(data[latkey].min())
                        geospatial_lat_max = float(data[latkey].max())
                    else:
                        geospatial_lat_min = ''
                        geospatial_lat_max = ''
                    metadata = {'coords': coords,
                                'variables': list(data.data_vars.keys()),
                                'time_variable': timekey,
                                'lon_variable': lonkey,
                                'lat_variable': latkey,
                                'geospatial_lon_min': geospatial_lon_min,
                                'geospatial_lon_max': geospatial_lon_max,
                                'geospatial_lat_min': geospatial_lat_min,
                                'geospatial_lat_max': geospatial_lat_max,
                                'time_coverage_start': time_coverage_start,
                                'time_coverage_end': time_coverage_end
                                }
                    file_intake.metadata = metadata

                file_intake.name = filename.split('/')[-1]
                lines += file_intake.yaml().strip('sources:')

            f = open(self.catalog_name, "w")
            f.write(lines)
            f.close()


    @property
    def catalog(self):

        if not hasattr(self, '_catalog'):

            self.write_catalog()
            catalog = intake.open_catalog(self.catalog_name)
            self._catalog = catalog

        return self._catalog


    @property
    def dataset_ids(self):
        '''Find dataset_ids for server.'''

        if not hasattr(self, '_dataset_ids'):
            self._dataset_ids = list(self.catalog)

        return self._dataset_ids


    def meta_by_dataset(self, dataset_id):
        '''Should this return intake-style or a row of the metadata dataframe?'''

        return self.catalog[dataset_id]


    @property
    def meta(self):
        '''Rearrange the individual metadata into a dataframe.'''

        if not hasattr(self, '_meta'):

            data = []
            if self.dataset_ids == []:
                self._meta = None
            else:
                # set up columns which might be different for datasets
                columns = ['download_url']
                for dataset_id in self.dataset_ids:
                    meta = self.meta_by_dataset(dataset_id)
                    columns += list(meta.metadata.keys())
                columns = set(columns)  # take unique column names

                self._meta = pd.DataFrame(index=self.dataset_ids, columns=columns)
                for dataset_id in self.dataset_ids:
                    meta = self.meta_by_dataset(dataset_id)
                    self._meta.loc[dataset_id]['download_url'] = meta.urlpath
                    self._meta.loc[dataset_id,list(meta.metadata.keys())] = list(meta.metadata.values())
                    # self._meta.loc[dataset_id][meta.metadata.keys()] = meta.metadata.values()
                    # data.append([meta.urlpath] + list(meta.metadata.values()))
                # self._meta = pd.DataFrame(index=self.dataset_ids, columns=columns, data=data)

        return self._meta


    def data_by_dataset(self, dataset_id):
        '''SHOULD I INCLUDE TIME RANGE?'''

        data = self.catalog[dataset_id].read()
#         data = data.set_index('time')
#         data = data[self.kw['min_time']:self.kw['max_time']]

        return (dataset_id, data)
#         return (dataset_id, self.catalog[dataset_id].read())


    # @property
    def data(self):
        '''Do I need to worry about intake caching?

        Data will be dataframes for csvs and
        Datasets for netcdf files.
        '''

        if not hasattr(self, '_data'):

            if self.parallel:
                num_cores = multiprocessing.cpu_count()
                downloads = Parallel(n_jobs=num_cores)(
                    delayed(self.data_by_dataset)(dataset_id) for dataset_id in self.dataset_ids
                )
            else:
                downloads = []
                for dataset_id in self.dataset_ids:
                    downloads.append(self.data_by_dataset(dataset_id))

#             if downloads is not None:
            dds = {dataset_id: dd for (dataset_id, dd) in downloads}
#             else:
#                 dds = None

            self._data = dds

        return self._data


class region(LocalReader):
#     def region(self, kw, variables=None):
#         '''HOW TO INCORPORATE VARIABLE NAMES?'''

    def __init__(self, kwargs):
        assert isinstance(kwargs, dict), 'input arguments as dictionary'
        lo_kwargs = {'catalog_name': kwargs.get('catalog_name', None),
                     'filenames': kwargs.get('filenames', None),
                     'parallel': kwargs.get('parallel', True)}
        LocalReader.__init__(self, **lo_kwargs)

        kw = kwargs['kw']
        variables = kwargs.get('variables', None)


        self.approach = 'region'

        self._stations = None

        # run checks for KW
        # check for lon/lat values and time
        self.kw = kw

# #         self.data_type = data_type
        if (variables is not None) and (not isinstance(variables, list)):
            variables = [variables]

        # make sure variables are on parameter list
        if variables is not None:
            self.check_variables(variables)

        self.variables = variables
#         # DOESN'T CURRENTLY LIMIT WHICH VARIABLES WILL BE FOUND ON EACH SERVER

#         return self


class stations(LocalReader):
#     def stations(self, dataset_ids=None, stations=None, kw=None):
#         '''
#         '''


    def __init__(self, kwargs):
        assert isinstance(kwargs, dict), 'input arguments as dictionary'
        loc_kwargs = {'catalog_name': kwargs.get('catalog_name', None),
                     'filenames': kwargs.get('filenames', None),
                     'parallel': kwargs.get('parallel', True)}
        LocalReader.__init__(self, **loc_kwargs)

        kw = kwargs.get('kw', None)
        dataset_ids = kwargs.get('dataset_ids', None)
        stations = kwargs.get('stations', None)

        self.approach = 'stations'



# #         self.catalog_name = os.path.join('..','catalogs',f'catalog_stations_{pd.Timestamp.now().isoformat()[:19]}.yml')

# #         # we want all the data associated with stations
# #         self.standard_names = None

#         # UPDATE SINCE NOW THERE IS A DIFFERENCE BETWEEN STATION AND DATASET
#         if dataset_ids is not None:
#             if not isinstance(dataset_ids, list):
#                 dataset_ids = [dataset_ids]
# #             self._stations = dataset_ids
#             self._dataset_ids = dataset_ids

# #         assert (if dataset_ids is not None)
#         # assert that dataset_ids can't be something if axds_type is layer_group
#         # use stations instead, and don't use module uuid, use layer_group uuid

#         if stations is not None:
#             if not isinstance(stations, list):
#                 stations = [stations]
#         self._stations = stations

#         self.dataset_ids


        # CHECK FOR KW VALUES AS TIMES
        if kw is None:
            kw = {'min_time': '1900-01-01', 'max_time': '2100-12-31'}

        self.kw = kw
#         print(self.kwself.)


#         return self
