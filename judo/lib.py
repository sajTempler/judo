class SQLiteConnection:
    def __init__(self, path, logger=None):
        """
        Class that abstracts the

        Args:
            path: (Path) Path to the database file
        """
        try:
            assert isinstance(path, Path)
        except AssertionError:
            if logger is not None:
                logger.warning("This would be better if path was of type Path")
            else:
                print("WARNING: path must be of class Path")

            path = Path(path)

        try:
            self.connection = sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True)
        except sqlite3.OperationalError:
            raise sqlite3.OperationalError(f'Unable to open {str(path.absolute())}')
        self.path = path
        self.logger = logger

    def query(self, query_string, values=None, empty_response=False, lastrowid=False):
        cursor = self.connection.cursor()
        if values is None:
            cursor.execute(query_string)
            self.connection.commit()
        else:
            cursor.execute(query_string, values)
            self.connection.commit()
        if empty_response and lastrowid:
            return cursor.lastrowid
        elif empty_response and not lastrowid:
            return
        elif lastrowid and not empty_response:
            return cursor.fetchall(), cursor.lastrowid
        else:
            return cursor.fetchall()

    def as_pandas(self, query_string, index_col='index', parse_dates=None, columns=None, params=None):
        """
        Return query as pandas data frame

        Args:
            query_string: SQL valid query
            index_col: Column to be used as index
            parse_dates: See pandas.read_sql parse_dates
            columns: See pandas.read_sql columns
            params: See pandas.read_sql params
        
        Returns: 
            A pandas.DataFrame
        """
        return pd.read_sql(query_string, self.connection, index_col=index_col, 
                           parse_dates=parse_dates, columns=columns, params=params)

    def as_geopandas(self, query_string, index_col='index', parse_dates=None, columns=None, intelligent=True, params=None):
        """
        Return query as geopandas data frame.

        The geometry columns in wkt format having a name that starts with epsg containing the epsg of the projection
        has to be retreived in the query.

        Args:
            query_string: SQL valid query
            index_col: Column to be used as index
            parse_dates: See pandas.read_sql parse_dates
            columns: See pandas.read_sql columns
            intelligent (bool, optional): If True it tries to change the string "geometry_column" for the name
                of the geometry column in the sql database.
            params: See pandas.read_sql params
        
        Returns:
            A geopandas.GeoDataFrame
        """
        if intelligent and 'geometry_column' in query_string:
            table_name = re.findall('from\s+([a-zA-Z][a-zA-Z0-9_]*|".*")(\s+|$)', query_string, re.IGNORECASE)[0][0]
            column_name = [x for x in self.as_pandas(
                f"PRAGMA TABLE_INFO('{table_name}')", index_col=None).name if x.startswith('epsg')][0]
            query_string = query_string.replace('geometry_column', f'"{column_name}"')
        df = pd.read_sql(query_string, self.connection, index_col=index_col, parse_dates=parse_dates, 
                         columns=columns, params=params)
        polygon_col = df.columns[df.columns.str.slice(0, 4) == 'epsg'][0]
        return gpd.GeoDataFrame(df.loc[:, df.columns != polygon_col],
                                crs={'init': polygon_col},
                                geometry=df[polygon_col].apply(shapely.wkt.loads))

    def commit(self):
        self.connection.commit()

    def add_table(self, name, df: pd.DataFrame, if_exists='replace'):
        """
        Add a dataframe to the table

        Args:
            name: Name of the table
            df: Dataframe to be written to
            if_exists(str): {‘fail’, ‘replace’, ‘append’}, default ‘fail’.

        """
        try:
            assert isinstance(df, pd.DataFrame)
        except AssertionError as e:
            if self.logger is not None:
                self.logger.exception(e)
            raise TypeError('df, Expected type pandas.DataFrame or geopandas.GeoDataFrame')

        if isinstance(df, gpd.GeoDataFrame):
            # Checks if there is a column starting by epsg because the geometry column will be stored with the name
            # of the projection
            if np.any(df.columns.str.slice(0, 4) == 'epsg'):
                raise ValueError("Column names cannot start by 'epsg'")
            df[df.crs['init']] = df.geometry.astype(str)
            df.drop(df.geometry.name, axis=1, inplace=True)

        df.to_sql(name=name, con=self.connection, if_exists=if_exists)

    def append_table(self, name, df: pd.DataFrame):
        """
        Append a dataframe to the table

        Args:
            name: Name of the table
            df: Dataframe to be written to
        
        Returns:
        """
        try:
            assert isinstance(df, pd.DataFrame)
        except AssertionError as e:
            if self.logger is not None:
                self.logger.exception(e)
            raise TypeError('df, Expected type pandas.DataFrame or geopandas.GeoDataFrame')
        
        if isinstance(df, gpd.GeoDataFrame):
            if np.any(df.columns.str.slice(0, 4) == 'epsg'):
                raise ValueError("Column names cannot start with 'epsg'")
            df[df.crs['init']] = df.geometry.astype(str)
            df.drop(df.geometry.name, axis=1, inplace=True)

        df.to_sql(name=name, con=self.connection, if_exists='append')

    def drop_table(self, table_name):
        try:
            self.query("drop table {}".format(table_name))

        except sqlite3.OperationalError:
            if self.logger is not None:
                self.logger.warning(f"Trying to drop a table that does not exist: {table_name}")

    def query_all(self, table_name):
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM {}".format(table_name))
        return cursor.fetchall()

    def query_all_as_pandas(self, table_name, index_col=None, parse_dates=None, columns=None, params=None):
        """
        Return query as pandas data frame

        :param table_name: Name of table to extract
        :param index_col: Column to be used as index
        :param parse_dates: See pandas.read_sql parse_dates
        :param columns: See pandas.read_sql columns
        :param params: See pandas.read_sql params
        :return: A pandas.DataFrame
        """
        return pd.read_sql('SELECT * FROM {}'.format(table_name), self.connection, index_col=index_col,
                           parse_dates=parse_dates, columns=columns, params=params)
    
    def count_rows(self, table_name):
        count = self.query('SELECT COUNT(*) FROM {}'.format(table_name))
        return count[0][0]
    
    def check_table_empty(self, table_name):
        if self.count_rows(table_name) == 0:
            return True
        else:
            return False

    def close(self):
        self.connection.close()