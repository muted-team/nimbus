// Immutable portable launcher: no Python/runtime dependencies before pointer selection.
#include <filesystem>
#include <fstream>
#include <regex>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <cstdlib>
#include <unistd.h>
#endif
namespace fs = std::filesystem;
static bool plain(const fs::path& path) {
#ifdef _WIN32
    auto a = GetFileAttributesW(path.c_str());
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_REPARSE_POINT);
#else
    return !fs::is_symlink(fs::symlink_status(path)) && fs::exists(path);
#endif
}
#ifdef _WIN32
static int launch(const std::wstring& extra_arguments) {
#else
static int launch(int argc, char** argv) {
#endif
    fs::path executable;
#ifdef _WIN32
    std::vector<wchar_t> buffer(32768);
    DWORD n = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (!n || n == buffer.size()) return 101;
    executable = fs::path(std::wstring(buffer.data(), n));
#else
    std::vector<char> buffer(65536);
    auto n = readlink("/proc/self/exe", buffer.data(), buffer.size());
    if (n < 0 || static_cast<size_t>(n) == buffer.size()) return 101;
    executable = fs::path(std::string(buffer.data(), n));
#endif
    const auto root = executable.parent_path();
    const auto pointer = root / ".nimbus-current";
    if (!plain(pointer) || !fs::is_regular_file(pointer)) return 104;
    std::ifstream stream(pointer, std::ios::binary);
    char pointer_bytes[81];
    stream.read(pointer_bytes, sizeof(pointer_bytes));
    std::string selected(pointer_bytes, static_cast<size_t>(stream.gcount()));
    stream.close(); // Do not hold the pointer open while waiting for the runtime (Windows).
    if (selected.empty() || selected.size() > 80) return 104;
    if (!selected.empty() && selected.back() == '\n') selected.pop_back();
    if (!std::regex_match(selected, std::regex("runtime-v[0-9]+\\.[0-9]+\\.[0-9]+"))) return 104;
    const auto runtimes = root / "runtimes";
    const auto runtime = runtimes / selected;
#ifdef _WIN32
    const auto childexe = runtime / "Nimbus-runtime.exe";
#else
    const auto childexe = runtime / "Nimbus-runtime";
#endif
    if (!plain(runtimes) || !plain(runtime) || !plain(childexe) || !fs::is_regular_file(childexe)) return 105;
#ifdef _WIN32
    if (!SetEnvironmentVariableW(L"NIMBUS_DATA_ROOT", root.c_str()) ||
        !SetEnvironmentVariableW(L"NIMBUS_BOOTSTRAP_ROOT", root.c_str())) return 106;
    std::wstring command = L"\"" + childexe.wstring() + L"\"";
    if (!extra_arguments.empty()) command += L" " + extra_arguments;
    STARTUPINFOW startup{}; startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(childexe.c_str(), command.data(), nullptr, nullptr, FALSE, 0,
                        nullptr, root.c_str(), &startup, &process)) return 107;
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD status = 1;
    GetExitCodeProcess(process.hProcess, &status);
    CloseHandle(process.hProcess);
    return static_cast<int>(status);
#else
    if (setenv("NIMBUS_DATA_ROOT", root.c_str(), 1) || setenv("NIMBUS_BOOTSTRAP_ROOT", root.c_str(), 1)) return 106;
    if (chdir(root.c_str())) return 107;
    std::vector<char*> arguments;
    arguments.push_back(const_cast<char*>(childexe.c_str()));
    for (int index = 1; index < argc; ++index) arguments.push_back(argv[index]);
    arguments.push_back(nullptr);
    execv(childexe.c_str(), arguments.data());
    return 107;
#endif
}
#ifdef _WIN32
int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR arguments, int) {
    int status = 109;
    try { status = launch(arguments ? arguments : L""); } catch (...) {}
    if (status >= 101 && status <= 109)
        MessageBoxW(nullptr, L"Nimbus could not start safely. Another instance may be running, or the installation is incomplete.", L"Nimbus", MB_OK | MB_ICONERROR);
    return status;
}
#else
int main(int argc, char** argv) { try { return launch(argc, argv); } catch (...) { return 109; } }
#endif
