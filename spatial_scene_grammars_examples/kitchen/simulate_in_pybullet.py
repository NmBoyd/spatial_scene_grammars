from spatial_scene_grammars_examples.kitchen.run_grammar import (
    rejection_sample_feasible_tree,
    project_tree_to_feasibility
)

from spatial_scene_grammars.serialization_sdf import serialize_scene_tree_to_package_and_single_sdf
import pybullet
import torch
import pyro

if __name__ == "__main__":
    torch.set_default_tensor_type(torch.DoubleTensor)
    pyro.enable_validation(True)

    scene_sdf_path = "/tmp/kitchen_scene.sdf"

    scene_tree, satisfied_clearance = rejection_sample_feasible_tree(num_attempts=1000)
    if not satisfied_clearance:
        print("WARNING: SCENE TREE NOT SATISFYING CLEARANCE")
    
    scene_tree, satisfied_feasibility = project_tree_to_feasibility(scene_tree, num_attempts=3)
    if not satisfied_feasibility:
        print("WARNING: SCENE TREE NOT SATISFYING FEASIBILITY, SIM MAY FAIL")

    serialize_scene_tree_to_package_and_single_sdf(
        scene_tree, scene_sdf_path,
        include_static_tag=True, 
        include_model_files=True,
        pybullet_compat=True
    )

    # Actual pybullet simulation starts here, above is just for
    # generating the SDF.
    physicsClient = pybullet.connect(pybullet.GUI)
    pybullet.setGravity(0,0,-9.81)
    pybullet.loadSDF(scene_sdf_path)
    pybullet.setRealTimeSimulation(1)


    while 1:
        pass
    pybullet.disconnect()