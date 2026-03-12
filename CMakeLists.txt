cmake_minimum_required(VERSION 3.10)
project(callscreener VERSION 1.0.0)

# Configure manifest with Clickable placeholders filled in
configure_file(manifest.json.in ${CMAKE_CURRENT_BINARY_DIR}/manifest.json)

# Install all app files into the click package
install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/manifest.json
    callscreener.apparmor
    callscreener.desktop
    DESTINATION ${CMAKE_INSTALL_PREFIX}
)

install(DIRECTORY qml   DESTINATION ${CMAKE_INSTALL_PREFIX})
install(DIRECTORY assets DESTINATION ${CMAKE_INSTALL_PREFIX})
