import os
import shutil

from conan import ConanFile
from conan.tools.apple import fix_apple_shared_install_name
from conan.tools.build import check_min_cppstd
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import copy, get, rmdir, export_conandata_patches, apply_conandata_patches
from conan.tools.microsoft import is_msvc, is_msvc_static_runtime
from conan.tools.scm import Git

required_conan_version = ">=2"


class OnnxConan(ConanFile):
    name = "onnx"
    version = "1.18.0.1"
    description = "Open standard for machine learning interoperability."
    license = "Apache-2.0"
    topics = ("machine-learning", "deep-learning", "neural-network")
    homepage = "https://github.com/onnx/onnx"
    url = "https://github.com/onnx/onnx"

    package_type = "library"
    settings = "os", "arch", "compiler", "build_type"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
        "disable_static_registration": [True, False],
    }
    default_options = {
        "shared": False,
        "fPIC": True,
        "disable_static_registration": True,
    }

    def export_sources(self):
        export_conandata_patches(self)
        # Export exactly the files git tracks, so untracked build trees and ignored local state
        # in the checkout never reach the recipe sources. Content is taken from the working tree.
        # Submodules are listed as gitlink entries (mode 160000) and skipped, checked out or not:
        # their content belongs to other repositories, and the build does not use it.
        repository_root = os.path.join(self.recipe_folder, "..")
        index_entries = Git(self, folder=repository_root).run("ls-files --cached -s -z")
        for entry in filter(None, index_entries.split("\0")):
            metadata, path = entry.split("\t", 1)
            if metadata.startswith("160000 ") or path.startswith("conan/"):
                continue
            destination = os.path.join(self.export_sources_folder, path)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(os.path.join(repository_root, path), destination, follow_symlinks=False)

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def configure(self):
        if is_msvc(self):
            del self.options.shared
            self.package_type = "static-library"
        if self.options.get_safe("shared"):
            self.options.rm_safe("fPIC")

    def layout(self):
        cmake_layout(self)

    def requirements(self):
        self.requires("protobuf/3.21.12.1", transitive_headers=True, transitive_libs=True)
        self.requires("zlib/1.3.1", override=True)

    def package_id(self):
        self.info.requires["protobuf"].full_package_mode()
        # The C++ standard is fixed by the recipe, not by the profile: generate() removes the
        # toolchain block that would turn compiler.cppstd into CMAKE_CXX_STANDARD and pins
        # CMAKE_CXX_STANDARD to 17. The artifact is identical for every compiler.cppstd, so it
        # must not split the package id.
        self.info.settings.rm_safe("compiler.cppstd")

    def validate(self):
        check_min_cppstd(self, 17)

    def build_requirements(self):
        self.tool_requires("protobuf/<host_version>")

    def source(self):
        if os.path.exists(os.path.join(self.source_folder, "CMakeLists.txt")):
            self.output.info("Sources found in source_folder (from export_sources), skipping download")
        else:
            self.output.info(f"Sources not found in {self.source_folder}, downloading tarball")
            get(self, **self.conan_data["sources"][self.version], strip_root=True)
        apply_conandata_patches(self)

    def generate(self):
        tc = CMakeToolchain(self)
        # Drop the language-standard block (CMAKE_CXX_STANDARD/EXTENSIONS/REQUIRED and
        # the C equivalents) and pin the standard: package_id() relies on compiler.cppstd
        # being inert for the build.
        tc.blocks.remove("cppstd")
        tc.variables["CMAKE_CXX_STANDARD"] = "17"
        tc.variables["CMAKE_CXX_STANDARD_REQUIRED"] = "ON"
        tc.cache_variables["ONNX_USE_PROTOBUF_SHARED_LIBS"] = self.dependencies.host["protobuf"].options.shared
        tc.cache_variables["BUILD_SHARED_LIBS"] = self.options.get_safe("shared", False)
        tc.cache_variables["ONNX_BUILD_PYTHON"] = False
        tc.cache_variables["ONNX_GEN_PB_TYPE_STUBS"] = False
        tc.cache_variables["ONNX_WERROR"] = False
        tc.cache_variables["ONNX_COVERAGE"] = False
        tc.cache_variables["ONNX_BUILD_TESTS"] = False
        tc.cache_variables["ONNX_USE_LITE_PROTO"] = self.dependencies.host["protobuf"].options.lite
        tc.cache_variables["ONNX_ML"] = True
        tc.cache_variables["ONNX_VERIFY_PROTO3"] = False
        if is_msvc(self):
            tc.cache_variables["ONNX_USE_MSVC_STATIC_RUNTIME"] = is_msvc_static_runtime(self)
        tc.cache_variables["ONNX_DISABLE_STATIC_REGISTRATION"] = self.options.disable_static_registration
        tc.generate()
        deps = CMakeDeps(self)
        deps.generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        copy(self, "LICENSE", src=self.source_folder, dst=os.path.join(self.package_folder, "licenses"))
        cmake = CMake(self)
        cmake.install()
        rmdir(self, os.path.join(self.package_folder, "lib", "cmake"))
        fix_apple_shared_install_name(self)
        copy(self, "onnx.proto", src=os.path.join(self.source_folder, "onnx"),
             dst=os.path.join(self.package_folder, "res", "onnx"))

    def package_info(self):
        self.cpp_info.set_property("cmake_file_name", "ONNX")
        requires = ["protobuf::libprotobuf"]
        defines = ["ONNX_NAMESPACE=onnx", "ONNX_ML=1"]
        if self.dependencies.host["protobuf"].options.lite:
            defines.append("ONNX_USE_LITE_PROTO=1")

        # onnx_proto: protobuf-generated types, depends on protobuf
        self.cpp_info.components["onnx_proto"].set_property("cmake_target_name", "ONNX::onnx_proto")
        self.cpp_info.components["onnx_proto"].set_property("cmake_target_aliases", ["onnx_proto"])
        self.cpp_info.components["onnx_proto"].libs = ["onnx_proto"]
        self.cpp_info.components["onnx_proto"].defines = defines
        self.cpp_info.components["onnx_proto"].requires = requires
        self.cpp_info.components["onnx_proto"].includedirs = ["include"]

        # libonnx: main ONNX library, depends on onnx_proto
        self.cpp_info.components["libonnx"].set_property("cmake_target_name", "ONNX::onnx")
        self.cpp_info.components["libonnx"].set_property("cmake_target_aliases", ["onnx"])
        self.cpp_info.components["libonnx"].libs = ["onnx"]
        self.cpp_info.components["libonnx"].defines = defines
        self.cpp_info.components["libonnx"].requires = ["onnx_proto"] + requires
        self.cpp_info.components["libonnx"].includedirs = ["include"]
