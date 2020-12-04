import matplotlib.pyplot as plt
import numpy as np
import os
import time

import torch
import torch.distributions.constraints as constraints
import pyro
import pyro.distributions as dist

from spatial_scene_grammars.nodes import *
from spatial_scene_grammars.rules import *
from spatial_scene_grammars.tree import *
from spatial_scene_grammars.sampling import *
from spatial_scene_grammars.factors import *


class OrbitalBody(GeometricSetNode):
    '''
    Orbital body that can produce some number of
    children in orbits around itself.

    (Modeled in 1d, in radial coordinates.)

    The body will produce children in a radius range based
    on its radius, and will produce children of significantly smaller
    radius than itself. Smaller radii bodies produce less children.
    '''

    class ChildProductionRule(ProductionRule):
        ''' Randomly produces a child planet from a parent planet. '''
        def sample_products(self, parent):
            # Child planet location and size is a function of the parent.
            # Both are saved associated with the rule to make writing
            # the neighborhood constraint more convenient.
            self.child_orbital_radius = pyro.sample("child_orbital_radius", 
                dist.Uniform(parent.min_child_orbital_radius, parent.max_child_orbital_radius))
            self.child_radius = pyro.sample("child_radius",
                dist.Uniform(parent.min_child_radius, parent.max_child_radius))
            child_x = parent.x + self.child_orbital_radius
            return [OrbitalBody(
                name="orbital_body",
                x=child_x,
                radius=self.child_radius)]

    def __init__(self, name, x, radius):
        self.radius = radius
        self.x = x
        super().__init__(name=name)

    def _setup(self):
        self.color = pyro.sample("color", dist.Uniform(0.0, 1.0))

        self.min_child_orbital_radius = self.radius*2.
        self.max_child_orbital_radius = self.radius*10.
        self.min_child_radius = self.radius * 0.01
        self.max_child_radius = self.radius * 0.1

        # Geometric rate increases linearly with
        # radius until saturating at 0.7 (i.e. 30%
        # chance of stopping at each new planet)
        # when the radius hits 0.7.
        assert self.radius > 0.
        reproduction_prob = torch.min(self.radius, torch.tensor(0.7))
        
        self.register_production_rules(
            production_rule_type=OrbitalBody.ChildProductionRule,
            production_rule_kwargs={},
            geometric_prob= 1.-reproduction_prob
        )


class ClearNeighborhoodConstraint(Constraint):
    def __init__(self):
        # Hard-coded "neighborhood" size
        self.neighborhood_size_ratio = 15.0
        super().__init__(lower_bound=torch.tensor(0.0),
                         upper_bound=torch.tensor(np.inf))

    def _eval_for_single_body(self, scene_tree, body):
        # Collect child local x and exclusion radii
        # by looking at the production rules under this body.
        child_rules = list(scene_tree.successors(body))
        child_local_x = [rule.child_orbital_radius for rule in child_rules]
        child_exclusion_radii = [rule.child_radius*self.neighborhood_size_ratio
                                 for rule in child_rules]
        # Prevent orbits of children from hitting the body itself, too.
        child_local_x.append(0.)
        child_exclusion_radii.append(body.radius)

        min_sdf = torch.tensor(np.inf)
        # Do N^2 comparison of all bodies
        for child_i in range(len(child_rules)):
            for child_j in range(child_i+1, len(child_rules)):
                if child_i == child_j:
                    continue
                dist = torch.abs(child_local_x[child_i] - child_local_x[child_j])
                sdf = dist - (child_exclusion_radii[child_j] + child_exclusion_radii[child_i])
                if sdf < min_sdf:
                    min_sdf = sdf
        return min_sdf
        
    def eval(self, scene_tree):
        # Returns signed distance between all exclusion zones
        # for any pairs of body.
        constraints = []
        all_bodies = scene_tree.find_nodes_by_type(OrbitalBody)
        signed_dist = [self._eval_for_single_body(scene_tree, body) for body in all_bodies]
        print("Min SDF: ", min(signed_dist))
        return min(signed_dist)

class PlanetCountConstraint(Constraint):
    def __init__(self):
        super().__init__(lower_bound=torch.tensor(2.0), upper_bound=torch.tensor(np.inf))
    def eval(self, scene_tree):
        # Counts how many planets the sun has
        sun = get_tree_root(scene_tree)
        print("Num planets: ", len(list(scene_tree.successors(sun))))
        return torch.tensor(len(list(scene_tree.successors(sun))))

class MoonCountConstraint(Constraint):
    def __init__(self):
        super().__init__(lower_bound=torch.tensor(1.0), upper_bound=torch.tensor(np.inf))
    def eval(self, scene_tree):
        # Counts how many moons each planet has
        simplified_tree = scene_tree.get_tree_without_production_rules()
        sun = get_tree_root(simplified_tree)
        planets = list(simplified_tree.successors(sun))
        if len(planets) == 0:
            return torch.tensor(np.inf)
        num_children_per_child = torch.tensor([
            len(list(simplified_tree.successors(planet)))
            for planet in planets
        ])
        print("Num children per child: ", num_children_per_child)
        return torch.min(num_children_per_child)

def sample_and_plot_solar_system():
    # Create clear-your-neighborhood constraint
    scene_tree, success = sample_tree_from_root_type_with_constraints(
            root_node_type=OrbitalBody,
            root_node_type_kwargs={
                "name":"sun",
                "radius": torch.tensor(100.),
                "x": torch.tensor(0.)
            },
            constraints=[
                ClearNeighborhoodConstraint(),
                PlanetCountConstraint(),
                MoonCountConstraint()
            ],
            max_num_attempts=1000
    )
    if not success:
        print("WARNING: SAMPLING UNSUCCESSFUL")

    sun = get_tree_root(scene_tree)
    # Override sun color to yellow
    sun.color = torch.tensor(1.0)
    all_bodies = scene_tree.find_nodes_by_type(OrbitalBody)
    
    planet_locations = np.vstack([planet.x.item() for planet in all_bodies])
    print(planet_locations.shape)
    planet_radii = [planet.radius.item() for planet in all_bodies]
    planet_colors = [planet.color.item() for planet in all_bodies]

    fig = plt.figure(dpi=300, facecolor='black').set_size_inches(13, 2)
    ax = plt.gca()
    cm = plt.get_cmap("viridis")

    print("Radii: ", planet_radii)

    plt.axhline(0., linestyle="--", color="white", linewidth=1, zorder=-1)
    # For each planet, plot the orbits of the children and the planet istelf
    for k, planet in enumerate(all_bodies):
        child_rules = list(scene_tree.successors(planet))
        for rule in child_rules:
            ax.add_artist(
                plt.Circle([planet_locations[k], 0.], rule.child_orbital_radius.item(), edgecolor=cm(planet_colors[k]),
                           fill=False, linestyle="--", linewidth=0.2)
            )
        # Planet core
        ax.add_artist(
            plt.Circle([planet_locations[k, :], 0.], planet_radii[k], color=cm(planet_colors[k]))
        )
    plt.xlim(-100, 1100)
    plt.ylim(-100, 100)
    ax.axis("off")
    ax.set_aspect('equal')
    plt.pause(0.1)

if __name__ == "__main__":
    torch.set_default_tensor_type(torch.DoubleTensor)
    pyro.enable_validation(True)

    for k in range(10):
        sample_and_plot_solar_system()
        plt.savefig("solar_system_%03d.png" % k,
                    facecolor=plt.gcf().get_facecolor(), edgecolor='none',
                    pad_inches=0., dpi=300, bbox_inches='tight')
        #plt.show()
        #plt.waitforbuttonpress()
        plt.close(plt.gcf())
    