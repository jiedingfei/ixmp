from copy import deepcopy
from functools import partial
from itertools import compress
from math import ceil

import pandas as pd
import xarray as xr

from .computations import aggregate


def combo_partition(iterable):
    """Yield pairs of lists with all possible subsets of *iterable*."""
    # Format string for binary conversion, e.g. '04b'
    fmt = '0{}b'.format(ceil(len(iterable) ** 0.5))
    for n in range(2 ** len(iterable) - 1):
        # Two binary lists
        a, b = zip(*[(v, not v) for v in map(int, format(n, fmt))])
        yield list(compress(iterable, a)), list(compress(iterable, b))


class Key:
    """A hashable key for a quantity that includes its dimensionality.

    Quantities in `ixmp.Scenario` can be indexed by one or more dimensions:

    >>> scenario.init_par('foo', ['a', 'b', 'c'], ['apple', 'bird', 'car'])

    Reporting computations for this `scenario` might use the quantity `foo`:
    1. in its full resolution, i.e. indexed by a, b, and c;
    2. aggregated over any one dimension, e.g. aggregated over c and thus
       indexed by a and b;
    3. aggregated over any two dimensions; etc.

    A Key for (1) will hash, display, and evaluate as equal to 'foo:a-b-c'. A
    key for (2) corresponds to `foo:a-b`, and so forth.

    Keys may be generated concisely by defining a convenience method:

    >>> def foo(dims):
    >>>     return Key('foo', dims.split(''))
    >>> foo('a b')
    foo:a-b

    """
    # TODO add 'method' attribute to describe the method(s) used to perform
    # (dis)aggregation, other manipulation
    # TODO add tags or other information to describe quantities computed
    # multiple ways
    # TODO cache repr() and only recompute when name/dims changed
    def __init__(self, name, dims=[]):
        self._name = name
        self._dims = dims

    @classmethod
    def from_str_or_key(cls, value):
        if isinstance(value, cls):
            return deepcopy(value)
        else:
            name, dims = value.split(':')
            return cls(name, dims.split('-'))

    def __repr__(self):
        """Representation of the Key, e.g. name:dim1-dim2-dim3."""
        return ':'.join([self._name, '-'.join(self._dims)])

    def __hash__(self):
        return hash(repr(self))

    def __eq__(self, other):
        return repr(self) == other

    def aggregates(self):
        """Yield (key, task) for all possible aggregations of the Key."""
        for agg_dims, others in combo_partition(self._dims):
            yield Key(self._name, agg_dims), \
                (partial(aggregate, dimensions=others), self)


def quantity_as_xr(scenario, name, kind='par'):
    """Retrieve quantity *name* from *scenario* as an xr.Dataset.

    Parameters
    ----------
    *kind* : 'par' or 'equ'
        Type of quantity to be retrieved.

    Returns
    -------
    dict of :class:'xarray.DataArray'
        Dictionary keys are 'level' (kind='par') or ('lvl', 'mrg')
        (kind='equ').
    """
    # NB this could be moved to ixmp.Scenario
    data = getattr(scenario, kind)(name)

    if isinstance(data, dict):
        # ixmp/GAMS scalar is not returned as pd.DataFrame
        data = pd.DataFrame.from_records([data])

    # Remove the unit from the DataFrame
    try:
        unit = pd.unique(data.pop('unit'))
        assert len(unit) == 1
        attrs = {'unit': unit[0]}
    except KeyError:
        # 'equ' are returned without units
        attrs = {}

    # List of the dimensions
    dims = data.columns.tolist()

    # Columns containing values
    value_columns = {
        'par': ['value'],
        'equ': ['lvl', 'mrg'],
        'var': ['lvl', 'mrg'],
    }[kind]

    [dims.remove(col) for col in value_columns]

    # Set index if 1 or more dimensions
    if len(dims):
        data.set_index(dims, inplace=True)

    # Convert to a series, then Dataset
    ds = xr.Dataset.from_dataframe(data)
    try:
        # Remove length-1 dimensions for scalars
        ds = ds.squeeze('index', drop=True)
    except KeyError:
        pass

    # Assign attributes (units) and name to each xr.DataArray individually
    return {col: ds[col].assign_attrs(attrs).rename(name)
            for col in value_columns}