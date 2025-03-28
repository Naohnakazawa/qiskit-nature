# This code is part of a Qiskit project.
#
# (C) Copyright IBM 2021, 2025.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""The Logarithmic Mapper."""

from __future__ import annotations
import operator

from collections import defaultdict
from fractions import Fraction
from functools import reduce

import numpy as np

from qiskit.quantum_info import SparsePauliOp
from qiskit.quantum_info.operators import Operator

from qiskit_nature.second_q.operators import SpinOp
from .spin_mapper import SpinMapper


class LogarithmicMapper(SpinMapper):
    r"""A mapper for Logarithmic spin-to-qubit mapping.
    In this local encoding transformation, each individual spin S system is represented via
    the lowest lying :math:`2S+1` states in a qubit system with the minimal number of qubits needed to
    represent :math:`>= 2S+1` distinct states [1].

    References:
        [1] S. V. Mathis, G. Mazzola and I. Tavernelli.
        Toward scalable simulations of lattice gauge theories on quantum computers.
        Phys. Rev. D, 102 (9), 094501 (2020). https://doi.org/10.1103/PhysRevD.102.094501
    """

    def __init__(self, *, padding: float = 1, embed_upper: bool = True) -> None:
        r"""
        Args:
            padding:
                When embedding a matrix into the upper/lower diagonal block of a
                :math:`2^n` by :math:`2^n` matrix ,where :math:`n` is the number of qubits, pads
                the diagonal of the block matrix with the value of ``padding``.

            embed_upper:
                This parameter sets whether the given matrix is embedded in the upper left hand
                corner or the lower right hand corner of the larger matrix.
                I.e. using ``embed_upper`` = `True` returns the matrix:

                .. math::
                    \begin{pmatrix}
                        \text{matrix} & 0 \\
                        0 & \text{padding} * I
                    \end{pmatrix}

                Using `embed_upper` = `False` returns the matrix:

                .. math::
                    \begin{pmatrix}
                        \text{padding} * I & 0 \\
                        0 & \text{matrix}
                    \end{pmatrix}

        """
        self._padding = padding
        self._embed_upper = embed_upper

    def _map_single(
        self, second_q_op: SpinOp, *, register_length: int | None = None
    ) -> SparsePauliOp:
        """Map spins to qubits using the Logarithmic encoding.

        Args:
            second_q_op: Spins mapped to qubits.

        Returns:
            Qubit operators generated by the Logarithmic encoding
        """
        if register_length is None:
            register_length = second_q_op.register_length

        qubit_ops_list: list[SparsePauliOp] = []

        # get logarithmic encoding of the general spin matrices.
        spinx, spiny, spinz, identity = self._logarithmic_encoding(second_q_op.spin)
        ordered_op = second_q_op.index_order()

        char_map = {"X": spinx, "Y": spiny, "Z": spinz}

        for terms, coeff in ordered_op.terms():

            mat = defaultdict(tuple)  # type: dict[int, tuple]

            for op, idx in terms:
                mat[idx] = mat[idx] @ char_map[op] if idx in mat else char_map[op]

            operatorlist = [mat[i] if i in mat else identity for i in range(register_length)]
            # Now, we can tensor all operators in this list
            qubit_ops_list.append(
                coeff * reduce(operator.xor, reversed(operatorlist))  # type: ignore[operator]
            )

        qubit_op = reduce(operator.add, qubit_ops_list)

        return qubit_op

    def _logarithmic_encoding(
        self, spin: Fraction | int
    ) -> tuple[SparsePauliOp, SparsePauliOp, SparsePauliOp, SparsePauliOp]:
        """The logarithmic encoding.

        Args:
            spin: Positive half-integer (integer or half-odd-integer) that represents spin.

        Returns:
            A tuple containing four SparsePauliOp.
        """
        spin_op_encoding: list[SparsePauliOp] = []
        dspin = int(2 * spin + 1)
        num_qubits = int(np.ceil(np.log2(dspin)))

        # Get the spin matrices
        spin_matrices = [
            SpinOp.x(spin).to_matrix(),
            SpinOp.y(spin).to_matrix(),
            SpinOp.z(spin).to_matrix(),
            np.eye(dspin),
        ]

        # Embed the spin matrices in a larger matrix of size 2**num_qubits x 2**num_qubits
        embedded_spin_matrices = [
            self._embed_matrix(matrix, num_qubits) for matrix in spin_matrices
        ]

        # Generate operators from these embedded spin matrices
        embedded_operators = [Operator(matrix) for matrix in embedded_spin_matrices]
        for op in embedded_operators:
            op = SparsePauliOp.from_operator(op)
            op.chop()
            spin_op_encoding.append(op)

        return (spin_op_encoding[0], spin_op_encoding[1], spin_op_encoding[2], spin_op_encoding[3])

    def _embed_matrix(
        self,
        matrix: np.ndarray,
        num_qubits: int,
    ) -> np.ndarray:
        r"""
        Embeds `matrix` into the upper/lower diagonal block of a :math:`2^\text{num_qubits}`
        by :math:`2^\text{num_qubits}` matrix and pads the diagonal of the upper left block matrix
        with the value of `padding`. Whether the upper/lower diagonal block is used depends on
        `embed_upper`. I.e. using `embed_upper` = `True` returns the matrix:

        .. math::
            \begin{pmatrix}
                \text{matrix} & 0 \\
                0 & \text{padding} * I
            \end{pmatrix}

        Using `embed_upper` = `False` returns the matrix:

        .. math::
            \begin{pmatrix}
                \text{padding} * I & 0 \\
                0 & \text{matrix}
            \end{pmatrix}

        Args:
            matrix: The matrix (2D-array) to embed.
            num_qubits: The number of qubits on which the embedded matrix should act on.

        Returns:
            If `matrix` is of size :math: `2^\text{num_qubits}`, returns `matrix`.
            Else it returns the block matrix (:math: `I` = identity)

        Raises:
            ValueError: If the passed matrix does not fit into the space spanned by num_qubits.
        """
        full_dim = 1 << num_qubits
        subs_dim = matrix.shape[0]

        dim_diff = full_dim - subs_dim
        if dim_diff == 0:
            full_matrix = matrix

        elif dim_diff > 0:
            if self._embed_upper:
                full_matrix = np.block(
                    [
                        [matrix, np.zeros((subs_dim, dim_diff), dtype=complex)],
                        [
                            np.zeros((dim_diff, subs_dim), dtype=complex),
                            np.eye(dim_diff) * self._padding,
                        ],
                    ]
                )
            else:
                full_matrix = np.block(
                    [
                        [
                            np.eye(dim_diff) * self._padding,
                            np.zeros((dim_diff, subs_dim), dtype=complex),
                        ],
                        [np.zeros((subs_dim, dim_diff), dtype=complex), matrix],
                    ]
                )

        else:
            raise ValueError(
                f"The given matrix does not fit into the space spanned by {num_qubits} qubits."
            )

        return full_matrix
